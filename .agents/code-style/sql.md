# PostgreSQL and migration style

These conventions are based on the database practices in SpectraBackend. They apply to PostgreSQL schema, migration, and query work in DocsApp.

## Migrations and schema evolution

- The Liquibase changelog in `backend/api/src/main/resources/db/changelog/` (master YAML plus numbered SQL changesets such as `001-initial-schema.sql`) is the source of truth for the schema. Put schema evolution there: one numbered changeset per change, never edit an already-applied one. `documentation/design/db.sql` and the ERD are generated from the changelog for review — treat them as derived artifacts, not as a migration mechanism.
- Each migration must have one coherent purpose, be safe for the deployment model, and state non-obvious invariants in SQL comments. Use a transaction when the database operation supports it; explicitly document exceptions such as concurrent index creation.
- For destructive or data-transforming changes, plan rollout order, backward compatibility with running application versions, backfill, locks, and recovery. Do not edit an already-applied migration; add a new migration.

## Tables, constraints, and indexes

- Use lowercase `snake_case` for schema objects. Name constraints and indexes after their table and purpose, such as `job_request_status_valid`, `media_owner_fk`, or `job_events_job_created_at_idx`.
- Declare primary keys, foreign keys, uniqueness, `NOT NULL`, defaults, and `CHECK` constraints close to the data model. Use `GENERATED ... AS IDENTITY` for surrogate numeric IDs unless a different identifier is a documented domain requirement.
- Encode critical data invariants in the schema where PostgreSQL can enforce them: status domains, non-negative/positive values, valid JSON object shapes, temporal ordering, ownership relationships, and uniqueness/idempotency keys.
- Model multi-tenant ownership explicitly. Where a child resource must belong to the same user/tenant as a parent, use composite keys/foreign keys or an equally strong database invariant when practical; always keep tenant predicates in application queries too.
- Index foreign-key and actual access paths deliberately. Use partial indexes for frequent filtered queries and GIN indexes for suitable JSONB/search workloads; do not add speculative indexes.

## Data handling and queries

- Use `timestamptz` for instants and UTC timestamps. Use `jsonb` only for documented extensible properties, with `CHECK (jsonb_typeof(...) = 'object')` when an object is required.
- Use `numeric` or integer minor units for exact quantities; never use floating point for values requiring exact comparison.
- Parameterize every query. Never build SQL by string interpolation from external input.
- Keep event/audit and financial-like histories append-only. Represent corrections with compensating events rather than overwriting completed records; protect write operations with idempotency keys where retries are possible.
- Avoid destructive `DROP`, broad `DELETE`, or unbounded `UPDATE` in routine migrations. State retention cleanup criteria explicitly and make cleanup jobs idempotent, observable, and tenant-safe.
