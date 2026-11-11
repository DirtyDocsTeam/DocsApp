# Language-specific code styles

Read the guide matching the language of the changed code in addition to [`../coding-style.md`](../coding-style.md).

- [`csharp.md`](csharp.md): conversion and validation workers (`WorkerC-N`, `WorkerV-N`).
- [`kotlin.md`](kotlin.md): Main API Plane (Quarkus, `backend/api`).
- [`python.md`](python.md): template and style-generation workers (`WorkerT-N`, `WorkerG-N`), automation, and tooling.
- [`typescript-react.md`](typescript-react.md): SPA, browser clients, and TypeScript libraries.
- [`go.md`](go.md): S3 Gateway Plane (`backend/s3-gateway`) and other Go services.
- [`sql.md`](sql.md): PostgreSQL migrations, queries, and schema changes.

If the repository later adopts another implementation language, add a guide here before introducing a broad new codebase in it.
