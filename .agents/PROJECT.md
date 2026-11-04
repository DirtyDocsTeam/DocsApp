# DocsApp — product baseline

DocsApp is a web service for preparing and formatting documents. It converts Markdown with attachments into DOCX and PDF (ODT is a lower-priority target), applies reusable styles, validates compliance with a selected style, and returns an output file with a validation report. The primary audience is authors; registered users retain their styles and job history, administrators operate the platform, and API users integrate batch processing from tools such as CI/CD or Obsidian.

## Core capabilities

- Registration and authentication with email verification; secure password storage (Argon2 or bcrypt); personal API quota and revocable API tokens.
- Personal styles and collections: create, edit, clone, delete, import, and export JSON/YAML configurations. Deleting a style must not alter completed jobs.
- Read-only system style presets, including versioned GOST presets; users can create copies, not mutate originals.
- Asynchronous conversion of Markdown plus attachments into DOCX/PDF, supporting images, tables, LaTeX, Mermaid, PlantUML, and code blocks.
- Style validation runs alongside conversion and classifies findings as errors or warnings; findings should be linkable to source locations in a preview.
- Browser preview with style switching where practical; template filling and reverse conversion are later-phase capabilities.
- An authenticated public API that returns a job ID and supports status tracking.
- Operational controls: queue/worker visibility, maintenance mode, audit logging, user blocking, and session/token invalidation.

## Reference architecture

- `frontend/`: SPA and browser-facing flows.
- `backend/`: REST API, authentication/OIDC boundary, job orchestration, conversion and validation workers, notification delivery, and style/template services.
- `devops/`: container, Kubernetes, storage, queue, observability, and deployment configuration.
- `documentation/`: product, architecture, QA, and media references. `documentation/media/db.sql` is the current schema draft.
- PostgreSQL persists users, tokens, styles, jobs, results, media metadata, and audit events.
- S3-compatible object storage holds inputs, attachments, outputs, and reports.
- RabbitMQ carries asynchronous job work; server-side workers parse, render, build, and validate documents.
- SSE or WebSocket communicates job progress to the frontend; polling remains a compatible fallback.
- Prometheus/Grafana and Loki provide metrics, dashboards, and logs.

## Deployment topology (additional architecture diagram)

The supplied deployment diagram refines the reference architecture with the following intended components:

- A React web client and an external API client (for example, an Obsidian integration) enter through an HAProxy-based ingress via REST and/or GraphQL.
- Keycloak acts as the identity provider, federating authentication with external identity providers such as GitHub or Google and persisting identity data in PostgreSQL.
- The main API plane is implemented in C# and owns application/job data in PostgreSQL. It validates access tokens with Keycloak and coordinates work through gRPC.
- A Go-based S3 gateway plane authorizes direct object-storage access after token validation and exposes separate external paths for web-static assets and media artifacts.
- SeaweedFS is the S3-compatible object store for user media, generated artifacts, and static web assets.
- The worker pool is composed of independently deployable workers: `Worker-C` (C# conversion), `Worker-V` (C# validation), `Worker-T` (Python templating), and `Worker-G` (Python style generation). Workers receive assignments from the API and publish completion/status information back to it.
- An external LLM (shown as DeepSeek) is used only by the optional style-generation worker; treat it as an explicit external-data-flow boundary.

The diagram labels the workload boundary as **DirtyDocs**; within this repository, use the product name **DocsApp** unless an approved rename is requested.

### Decisions to validate before implementation

- The earlier architecture lists RabbitMQ and server-side SSE/WebSocket notifications, while this topology draws API-to-worker gRPC coordination and does not show notification infrastructure. Confirm whether RabbitMQ remains the durable job queue and how client progress events are delivered.
- Confirm whether GraphQL is required in addition to REST. The public API must still publish a clear OpenAPI/Swagger contract for REST endpoints if that requirement remains in scope.
- Confirm the exact trust model for direct S3 access: use short-lived, job- and tenant-scoped signed URLs or temporary credentials; never proxy unrestricted bucket access to clients.
- Before enabling the external LLM, define consent, data minimization, redaction, retention, and an approved legal basis. Documents or personal data must not be sent to it by default.

## Job lifecycle

Typical conversion flow:

1. API validates the main file and attachments (main file up to 10 MB; attachments up to 150 MB total) and stores them under a job-scoped prefix.
2. It creates a queued job, writes an audit event, publishes a message, and returns `202 Accepted` with a job ID/status URL.
3. A worker advances the job through `QUEUED`, `PARSING`, `RENDERING`, `BUILDING`, and `VALIDATING` as applicable.
4. Terminal states are `COMPLETED`, `COMPLETED_WITH_WARNINGS`, `FAILED`, and `VALIDATION_FAILED`. Store result/report references and make signed download URLs available only for valid results.
5. Notify clients about status changes; expose clear localized errors rather than internal stack traces.

Processing must be safe to retry: avoid duplicate outputs/events when jobs or messages are redelivered, keep tenant ownership checks on every resource access, and record enough telemetry for diagnosis.

## Security, privacy, and retention

- Enforce logical tenant isolation for users, styles, jobs, media, API tokens, and signed URLs.
- Use TLS 1.3 for network traffic. Do not expose object-storage keys or internal worker details to clients.
- Hash passwords with Argon2 or bcrypt and reject trivially weak passwords such as `12345`, `password`, and `qwerty`.
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

The database schema is an initial draft and may contain incomplete constraints or naming inconsistencies. Treat it as a design reference, validate it before use, and do not assume it is migration-ready.
