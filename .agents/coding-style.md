# Common code style

These rules apply to all DocsApp code regardless of language. They are adapted from the shared coding conventions used in the IgdrasilEngine repository; language-specific rules supplement them in [`code-style/`](code-style/).

## Core principles

- Prefer one primary public type, component, module, or responsibility per source file. Keep files small and focused; extract a helper rather than creating a catch-all utility module.
- Preserve the established style of every file you change: its formatting, import arrangement, naming pattern, error-handling idioms, and layout. Do not reformat legacy code or migrate syntax merely because a newer convention exists.
- Make narrow changes. Do not combine unrelated cleanup, renames, dependency upgrades, or architectural rewrites with a feature or bug fix.
- Name things after the product domain and their real responsibility. Prefer names such as `ConversionJob`, `StyleValidator`, and `SignedDownloadUrl` over vague names such as `Manager`, `Helper`, `Data`, or numbered variants.

## Structure and readability

- Keep control flow direct. Prefer guard clauses and early returns to deep nesting.
- Keep functions cohesive. Extract independently testable or reusable logic; do not extract trivial one-line fragments solely to reduce line count.
- Prefer clear loops or explicit steps when they communicate intent better than a dense functional chain or abstraction.
- Avoid speculative abstractions and framework-like layers unless the surrounding module already uses them or the requirement demonstrably needs them.
- Keep imports/dependencies at the file boundary and remove unused ones. Do not introduce a dependency for a small capability already supplied by the platform or project.

## API, contracts, and errors

- Validate inputs at the boundary where they enter the system. State preconditions in code and return or throw errors that identify the failed operation without exposing internals or sensitive data.
- Keep nullability, optionality, and error results honest. Do not suppress compiler/type-checker warnings or use unsafe casts/non-null assertions without an adjacent, enforced invariant.
- Preserve public contracts and backward compatibility unless the change explicitly authorizes a breaking change. Version external API and persisted-data changes deliberately.
- Document new public API, non-obvious business rules, security boundaries, and surprising trade-offs. Do not mass-add comments to untouched code. Comments explain *why*, not a restatement of code.
- Make asynchronous behavior explicit: cancellation, timeout, retryability, idempotency, and ownership of resources must be clear at job, worker, storage, and network boundaries.

## Tests and verification

- Add or update focused tests for changed behavior, especially authorization, tenant isolation, retention, conversion status transitions, validation results, and failure cases.
- Prefer direct, readable assertions and test names that describe the behavior. Keep test helpers small and local until real reuse is established.
- Run the smallest relevant formatter, linter, type-checker, build, and test suite available; report any check that was not run.

## Prohibited shortcuts

- Do not log credentials, tokens, document contents, signed URLs, personally identifiable information, or unredacted third-party responses.
- Do not return stack traces, implementation details, or raw upstream errors to ordinary users.
- Do not introduce silent data loss, broad catch-all error handling, unbounded retries, or global mutable state in request/job processing.
- Do not alter generated files manually when their source or generator is available.
