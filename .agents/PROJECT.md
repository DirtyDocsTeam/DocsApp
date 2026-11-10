# DocsApp — product baseline

DocsApp is a web service for preparing and formatting documents. It converts Markdown with attachments into DOCX and PDF (ODT is a lower-priority target), applies reusable styles, validates compliance with a selected style, and returns an output file with a validation report. The primary audience is authors; registered users retain their styles and job history, administrators operate the platform, and API users integrate batch processing from tools such as CI/CD or Obsidian.

This file states product intent only. The architecture is defined by the C4 context diagram in [`documentation/design/context.drawio`](../documentation/design/context.drawio) and decoded in [`documentation/design/design.md`](../documentation/design/design.md); where this file says less, the diagram wins.

## Core capabilities

- Sign-in through Keycloak (the C4 `IDProvider`): registration, login, email verification, password policy, MFA, and federation with GitHub or Google are Keycloak's responsibility. The application validates access tokens and never stores credentials, password hashes, or its own sessions; per-user API quota and revocable API tokens remain application concerns.
- Personal styles and collections: create, edit, clone, delete, import, and export JSON/YAML configurations. Deleting a style must not alter completed jobs.
- Read-only system style presets, including versioned GOST presets; users can create copies, not mutate originals.
- Asynchronous conversion of Markdown plus attachments into DOCX/PDF, supporting images, tables, LaTeX, Mermaid, PlantUML, and code blocks.
- Style validation runs alongside conversion and classifies findings as errors or warnings; findings should be linkable to source locations in a preview.
- Browser preview with style switching where practical; template filling and reverse conversion are later-phase capabilities.
- An authenticated public API that accepts a job and returns a job ID with a status URL; clients read status by polling it.
- Operational controls: worker visibility, maintenance mode, audit logging, user blocking, and session/token invalidation.

## Architecture (expanded from C4)

- `frontend/`: React SPA. Together with the external API client (for example an Obsidian integration) it reaches the system through Ingress using REST or GraphQL.
- `backend/api/`: the C4 **Main API Plane** — Quarkus on the JVM, written in Kotlin. Owns application and job data in PostgreSQL, validates tokens with Keycloak (`REST [Token validate]`), serves GraphQL (`GQL [Main work]`) and REST, and coordinates the worker pool over gRPC.
- `backend/s3-gateway/`: the C4 **S3 Gateway Plane** — Go. Exposes separate external paths for web-static assets and media artifacts, asks the API about the token and the object path over gRPC (`[ID → S3://path, Token validate]`), and reaches the store over the internal S3 path.
- Workers are independent deployments, not modules of the API binary: `WorkerC-N` conversion (C#), `WorkerV-N` validation (C#/C++), `WorkerT-N` templating (Python), `WorkerG-N` style generation (Python).
- `devops/`: container, Kubernetes, storage, and deployment configuration, plus operations tooling (Prometheus/Grafana, Loki) that the C4 context diagram does not draw.
- `documentation/`: product, architecture, QA, and media references.
- PostgreSQL (C4 `Main Database`) persists identity data, users, API tokens, styles, jobs, results, media metadata, and audit events.
- SeaweedFS (C4 `Object storage`) holds inputs, attachments, outputs, and static web assets. Clients never address it directly: they receive a path or a signed link from the S3 gateway.
- HAProxy Ingress is the single entry point: REST/GraphQL to the API, OIDC to Keycloak, object paths to the S3 gateway.

## Decisions taken from C4

These used to be open questions; the diagram settles them, so they are not revisited without changing the diagram.

- **No message broker.** Work reaches workers as `gRPC [Job assign]` from the API; results and status come back as `gRPC [Announce]`. Retry and idempotency therefore belong to the gRPC assignment, not to a queue consumer.
- **No server-side push to clients.** C4 draws no notification channel, so progress is polled through the API. Introducing SSE or WebSocket is an architecture change: record it in C4 first.
- **Two client-facing surfaces.** REST serves external API clients and integrations; GraphQL serves the SPA and clients that need flexible selection. Both enter through Ingress.
- **Identity lives in Keycloak.** The API is a resource server: token validation only, no credential storage and no local user passwords.
- **The API plane is Quarkus/JVM, not .NET.** C# and C++ appear only inside the conversion and validation workers.
- **Calling the S3 gateway goes through the API.** The gateway asks the API to validate the token and resolve the identifier to an S3 path; the API never proxies object bytes itself.
- **The external LLM is reachable only from `WorkerG-N`.** Any other outbound traffic is an architecture change, not an implementation detail.

## Open decisions

- **Trust model for direct S3 access.** Short-lived, job- and tenant-scoped signed URLs or temporary credentials; never proxy unrestricted bucket access to clients. The exact TTL and scope still need to be written down.
- **External LLM usage.** Define consent, data minimization, redaction, retention, and an approved legal basis before enabling it. Documents and personal data must not be sent to it by default.
- **REST contract publication.** If external clients are in scope, the REST surface must publish an OpenAPI contract; the generated `documentation/api/` pages are the current snapshot, not a signed-off contract.

## Job lifecycle

Typical conversion flow:

1. API validates the main file and attachments (main file up to 10 MB; attachments up to 150 MB total) and stores them under a job-scoped prefix.
2. It creates a queued job, writes an audit event, assigns the job to a worker over gRPC, and returns `202 Accepted` with a job ID and status URL.
3. A worker advances the job through `QUEUED`, `PARSING`, `RENDERING`, `BUILDING`, and `VALIDATING` as applicable, reporting progress back over gRPC.
4. Terminal states are `COMPLETED`, `COMPLETED_WITH_WARNINGS`, `FAILED`, and `VALIDATION_FAILED`. Store result/report references and make download links available only for valid results.
5. The client polls the status URL; status transitions and audit events are persisted so a retry returns the same answer. Expose clear localized errors rather than internal stack traces.

Processing must be safe to retry: avoid duplicate outputs and duplicate audit events when an assignment is redelivered or a worker restarts, keep tenant ownership checks on every resource access, and record enough telemetry for diagnosis.

## Security, privacy, and retention

- Enforce logical tenant isolation for users, styles, jobs, media, API tokens, and signed links.
- Use TLS 1.3 for network traffic. Do not expose object-storage keys, internal worker details, or the internal S3 path to clients.
- Credentials, password policy, and weak-password rejection (`12345`, `password`, `qwerty`) are enforced in Keycloak, not in the application.
- Rate-limit API tokens at 100 requests per minute and invalidate active sessions/tokens when an administrator blocks a user.
- Delete processing outputs and source documents after 3 hours; delete attachments after 7 days. Ensure cleanup is observable and idempotent.
- Follow 152-FZ-related data-handling requirements; do not transfer user data to third parties without an approved design and legal basis.

## Quality targets

- For lightweight previews, target p95 below 100 ms; use asynchronous processing when that is not feasible.
- Target conversion completion within 5 seconds for files up to 1 MB and 15 seconds for files up to 10 MB where supported content permits.
- Target 99% SLA and MTTR below 15 minutes; alert on processing times over the relevant SLA.
- Support Safari, Chromium, and Firefox from 360 px to 3840 px at DPR 1–4.
- Test the main conversion path with at least 70% coverage and keep test cases/review artifacts in the team's QA process.

## Known draft status

- The database schema is an initial draft: constraints are incomplete (a `CHECK` clause referencing a non-existent column, tokens created already expired, statuses as unconstrained `varchar`) and it is not migration-ready. The Liquibase changelog in `backend/api/src/main/resources/db/changelog/` is the source of truth for the schema; `documentation/design/db.sql` is generated from it.
- `documentation/api/` pages are generated snapshots of what the code declares today; they are not a published contract until the REST surface is signed off.
