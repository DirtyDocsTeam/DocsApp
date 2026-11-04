# Go style

- Use `gofmt` and project linters; their output is authoritative. Keep package names short, lowercase, and domain-specific.
- Export only the API needed outside the package. Use Go naming conventions: exported identifiers are `PascalCase`, unexported identifiers are `camelCase`; avoid redundant stuttering such as `gateway.GatewayService`.
- Accept `context.Context` as the first parameter of request-scoped or blocking operations and propagate cancellation/deadlines to outbound calls and storage operations.
- Return errors rather than panicking for operational or input failures. Wrap errors with operation context using `%w`, but do not leak credentials, tokens, object paths, or tenant data.
- Close resources promptly with `defer` immediately after successful acquisition when the function scope is appropriate. Check errors from writes, flushes, and closes when they can affect correctness.
- Define small interfaces at the consuming boundary when needed for tests or alternate implementations. Avoid large general-purpose interfaces and package-level mutable globals.
- Serialize and validate authorization claims, object keys, and signed URL parameters at the gateway boundary; do not trust upstream client-provided tenant or path identifiers.
