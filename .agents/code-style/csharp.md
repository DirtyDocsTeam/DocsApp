# C# style

C# is used by the conversion (`WorkerC-N`) and validation (`WorkerV-N`) workers, not by the API plane — the Main API Plane is Quarkus/JVM (see [`kotlin.md`](kotlin.md)).

- Follow the local project's `.editorconfig`, analyzers, formatter, nullable settings, and SDK target when present; they override this guide.
- Keep one primary type per file. Use file-scoped namespaces and top-level `using` directives in new code unless the target project consistently uses another form.
- Use PascalCase for namespaces, types, methods, properties, events, and public fields. Use camelCase for parameters and local variables; use `_camelCase` for private fields when the module does so.
- Prefer `var` when the right side makes the type evident; otherwise declare the type explicitly when it improves reading, numeric clarity, or API comprehension.
- Prefer immutable `record`/`record class` or `init`-only DTOs for transport and configuration data when consistent with the module. Avoid mutable shared DTOs.
- Use `async` APIs end-to-end for I/O. Name asynchronous methods with an `Async` suffix, accept and propagate `CancellationToken` at public I/O boundaries, and avoid sync-over-async (`.Result`, `.Wait()`).
- Use nullable reference types honestly. Avoid `!`; check/validate the invariant instead. Throw a concrete exception for violated programmer preconditions and return a structured domain/API error for expected user input or operational failure.
- Document new public and protected members with XML comments where the intent, parameters, return value, or exception behavior is not obvious. Do not rewrite legacy documentation unnecessarily.
- Favor dependency injection and explicit interfaces at external boundaries (storage, queue, identity, clock); do not introduce interfaces for tiny internal implementation details without a testing or polymorphism need.
