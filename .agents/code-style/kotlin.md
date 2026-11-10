# Kotlin/JVM style

These conventions apply to the C4 Main API Plane (`backend/api`, Quarkus on the JVM in Kotlin) and to any later Kotlin/JVM service. They are based on the Kotlin practices in SpectraBackend. The local Gradle configuration, Kotlin compiler settings, framework conventions, and formatter/linter take precedence.

## Layout and naming

- Keep one primary public class, interface, or top-level responsibility per file. Use the package structure to express bounded contexts such as `auth`, `jobs`, `styles`, or `storage`.
- Use `PascalCase` for classes, interfaces, enums, and objects; use `camelCase` for functions, properties, and parameters; use `UPPER_SNAKE_CASE` only for true constants.
- Prefer Kotlin's concise, idiomatic syntax when it stays clear: primary constructors, immutable `val` by default, data classes for value/transport objects, expression bodies for trivial functions, and trailing commas in multi-line declarations.
- Avoid `!!`, platform types leaking through public APIs, unchecked casts, and mutable global state. Make nullability explicit and validate values at the boundary.

## Services, dependencies, and I/O

- Use constructor injection for dependencies. Keep infrastructure collaborators explicit (for example, database context, object storage, identity client, clock, queue publisher); do not use service locators.
- Keep request/job execution transactional where an operation changes related durable state. Document the locking, idempotency key, and retry behavior for stateful worker or queue operations.
- Use coroutines only when the selected framework and dependent libraries are coroutine-safe end-to-end. Do not block event-loop threads or bridge asynchronous code with ad-hoc blocking calls.
- Pass a request/job cancellation context or the framework's equivalent through I/O boundaries. Apply timeouts to outbound identity, storage, LLM, and worker calls.

## Persistence and API boundaries

- When using jOOQ, compose typed queries with generated tables/fields; do not construct dynamic SQL strings. Keep transaction scope and row-lock intent close to the mutation.
- Map persistence records to explicit domain/API models at the boundary. Do not expose generated database records or internal exception types from REST/GraphQL/gRPC endpoints.
- Validate and normalize external input before persistence. Convert expected validation and conflict failures into stable, localized client errors; preserve operational causes in structured server logs without logging secrets or document contents.
- Use `require`/`check` for programmer preconditions or internal invariants. Do not use them as the final representation of an ordinary user-facing HTTP error.

## Documentation and tests

- Document public APIs and non-obvious invariants with KDoc, particularly authorization scope, transaction semantics, privacy behavior, and retry/idempotency guarantees.
- Prefer direct JUnit/Kotlin assertions and scenario-focused test names. Test success, authorization, conflict, timeout/retry, and failure paths around each external boundary.
