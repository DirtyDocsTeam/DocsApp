# API, jobs, media, and theme lifecycle

## Intent

Complete the public API surface around OIDC access, worker jobs, media intake, themes, and retention. Browser clients use GraphQL and WebSocket subscriptions; external clients use REST plus OIDC or API tokens. The API owns durable state and authorization; the S3 Gateway owns object bytes; workers process only fully assembled jobs.

## Constraints

- Keycloak owns registration, authentication, refresh, password policy, and sessions. DocsApp stores neither passwords nor locally issued session tokens.
- Media and jobs are tenant isolated at the authorization boundary. Bytes use a global content-addressed cache keyed by hash: a cache hit may avoid re-upload even when another user first supplied identical bytes, but it never grants access to that user's job/result metadata or storage path.
- The present Main API ↔ S3 Gateway gRPC connection is not deployed. This change defines protobuf contracts and an internal port with explicit TODO implementations; it must not pretend that files can be uploaded yet.
- C4 currently forbids client push. This design changes that decision: GraphQL subscriptions use WebSocket and receive events from a PostgreSQL-backed outbox, without introducing a message broker.

## Approach

### Authentication: OIDC facade

REST endpoints are a browser-facing facade over Quarkus OIDC:

- `POST /auth/register` starts Keycloak's registration action;
- `POST /auth/login` starts the authorization-code flow;
- `POST /auth/refresh` refreshes the existing OIDC session only;
- `POST /auth/logout` invalidates the local OIDC session and delegates provider logout.

They never accept a password or return a provider refresh token. API clients authenticate with a verified OIDC bearer token or the opaque application API token already supported by the API.

The facade uses only HTTPS redirects and the Quarkus OIDC HTTP-only secure session cookie: register/login return `303 See Other` to the provider flow, the provider callback is handled by Quarkus, refresh returns `204 No Content` after refreshing the existing session, and logout returns `204 No Content` after the provider session is ended. API-token callers receive `401` from these endpoints; no browser cookie is created for them. State and nonce validation remain Quarkus OIDC responsibilities.

### Job and media intake

`createJob` accepts one primary-media hash and zero or more attachment hashes. In one transaction it creates a job in `WAITING_FOR_MEDIA`, records idempotent expected-media rows scoped to that job/user, and links media already present in the global content-addressed cache. Its result contains the job and the distinct `missingMediaHashes`.

For every missing hash the API calls the `ExpectedMediaGateway` port. The future implementation sends an authenticated gRPC expectation to the S3 Gateway containing the user, job, hash, expiry, and one-time upload capability. The gateway must accept an upload only for a live expectation, calculate and compare the content hash itself, and report receipt to the API over gRPC. Until the connection exists, the port has an explicit TODO and no upload URL is issued.

The receipt endpoint is idempotent by `(user, hash, storage path)`. It creates or reuses that user's media record, resolves every matching expected-media row, emits a media-received event, and moves a job to `QUEUED` only when all required media is present. Only then can worker assignment occur.

`deleteJob` is a logical deletion: it cancels work that has not reached a terminal worker state, sets `deleted_at`, hides the job from ordinary queries, and emits a deletion event. Durable events and media remain available to retention cleanup rather than being hard-deleted during a request.

The job state machine is `WAITING_FOR_MEDIA → QUEUED → PROCESSING → PARSING/RENDERING/BUILDING/VALIDATION → terminal`. `CANCELLED` is terminal and can be reached from every non-terminal state; deleted jobs accept no new transitions. Gateway and worker reports include a delivery idempotency key. A repeated key with the same payload replays the recorded result; the same key with a different payload returns a conflict and records no state change.

### Media reads and retention

Media reads are GraphQL queries scoped through the owning job/result. A client sees stable API identifiers and Gateway-facing public IDs, never `storage_path`. `MediaQuery` returns only media reachable from one of the viewer's non-deleted jobs.

The media schema gains owner, cache classification, and deletion state. `delete_at` is the expiry lease of the cached object, not a deadline inherited from a particular job: every receipt, attachment, worker assignment, or other use updates `updated_at` and recalculates `delete_at` from that use's role. Primary documents and results receive `updated_at + 3 hours`; attachments receive `updated_at + 7 days`. No TTL column is stored: the current TTL is derivable as `delete_at - updated_at`. The future Gateway contract likewise acquires or renews this lease before serving or transferring bytes. A Quartz cleanup job selects due, unreferenced rows with `FOR UPDATE SKIP LOCKED`, rechecks the lease while holding the row lock, requests object deletion through the same Gateway port, then marks/deletes metadata only after success. It is safe to retry and emits structured lifecycle events. `isNonCacheable` media becomes due immediately after its final consuming job is terminal; it is not removed while another live job still references it.

### Theme API

Existing page/search/get queries are retained and made explicit as public versus personal. Add mutations to create, update, and logically delete themes; updates use optimistic `updatedAt` preconditions. A theme receives an explicit owner so mutation authorization does not rely on ambiguous collection membership. The theme owner (or an administrator) may update/delete their theme regardless of their collection role; collection roles continue to govern collection membership and visibility, including whether that user can manage other themes in the collection. Public visibility affects reading only. Each mutation records a theme event and publishes a subscription notification.

### Subscriptions

Expose owner-authorized WebSocket subscriptions for job status, media receipt, and theme changes. Every state-changing transaction writes an outbox row and calls PostgreSQL `NOTIFY` only after the event is durable. Each API replica listens, reloads the event by id, and publishes it to its local GraphQL subscription streams. Consumers must re-query after reconnect; the event stream is notification, not a durable replay protocol.

Outbox payloads contain only an event id, aggregate type/id, owner id, event type, schema version, and timestamp; detailed data is read from the authorized projection. `NOTIFY` carries only the event id, so PostgreSQL's payload limit is irrelevant. Listener delivery is at-least-once and local streams de-duplicate by event id.

## Schema and contracts

- Add `WAITING_FOR_MEDIA`, `CANCELLED`, `deleted_at`, worker-delivery metadata, and idempotency keys to jobs.
- Add `job_expected_media` with user, job, hash, role (`PRIMARY`/`ATTACHMENT`), state, expiry, and receipt metadata.
- Add safe retention/deletion state to media; enforce global hash uniqueness for the content-addressed cache while keeping user/job ownership only in the references and authorization checks.
- Add `themes.owner_user_id`; it is the authority for theme mutation/deletion and deliberately coexists with collection roles.
- Add `domain_event_outbox`; retain `job_events` as the job audit log and add a theme event record or event type.
- Extend `media.proto` with expectation and receipt messages/services; extend `worker.proto` with assignment and status announcement messages/services. Both services authenticate internal callers and include idempotency keys.
- Add GraphQL input/result types for jobs, media, themes, page results, and subscription events. Add REST resources for the OIDC facade. API documentation is generated from annotations/proto rather than edited directly.

Internal gRPC uses mTLS service identity, a ten-second deadline, and additive protobuf evolution only (new optional fields/message types; never renumber or reuse fields). Failed Gateway deletion is retried with bounded exponential backoff; metadata remains intact, moves to a visible deletion-failed state after the retry budget, and emits metrics/alerts.

## Authorization and failure behavior

- OIDC users and API-token scopes must authorize every mutation and subscription at subscription creation and event dispatch.
- `jobs.edit` is required for job create/delete; `jobs.read` for reads/subscriptions; `themes.edit`/`delete` for theme mutations; `themes.read` for theme reads/subscriptions.
- Missing primary media returns a job plus hashes to upload; it is not assigned to a worker. Expired/unknown/foreign expectations return a stable forbidden or conflict error without leaking object existence.
- Optimistic-update conflicts, duplicate idempotency keys with different payloads, illegal status transitions, and late worker/gateway reports are stable conflict responses and are recorded for operations.

## Non-goals

- Implementing byte upload/download or an active Main API ↔ S3 Gateway gRPC channel.
- Introducing a message broker, local passwords, or token issuance by DocsApp.
- Durable replay/catch-up for WebSocket subscriptions.

## Delivery order

1. Update C4 for WebSocket subscriptions and generated API documentation configuration.
2. OIDC REST facade.
3. Schema, outbox, job command service, expected-media GraphQL contract, and gRPC skeleton.
4. Worker status/assignment command surface, job/media reads, deletion, and subscriptions.
5. Theme ownership, mutations, subscriptions, and public/personal page-result contract.
6. Cache cleanup scheduler, observability, and integration tests.
