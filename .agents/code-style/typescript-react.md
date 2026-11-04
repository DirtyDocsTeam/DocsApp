# TypeScript and React style

- Use TypeScript strictness configured by the project; do not bypass it with `any`, broad casts, `@ts-ignore`, or non-null assertions unless a local invariant is checked directly beside the usage.
- Use `PascalCase` for React components, types, and interfaces; `camelCase` for variables, functions, hooks, props, and event handlers; name hooks with `use`.
- Keep one primary component or hook per file. Place tightly coupled types, styles, and tests according to the local feature structure rather than creating a global dump directory.
- Prefer typed API client contracts generated from or aligned with the published server contract. Validate untrusted runtime data at the boundary; static TypeScript types alone do not validate network input.
- Keep UI state local by default. Promote state only when multiple consumers need it; do not add a global state framework for a single feature.
- Treat rendering as pure. Put network calls, subscriptions, timers, and cleanup in effects or the project's data-fetching abstraction; cancel/ignore obsolete requests and clean up subscriptions.
- Show localized, actionable user errors. Never expose raw server errors, tokens, signed URLs, or document contents in logs, DOM attributes, or analytics.
- Follow accessible semantic HTML, keyboard interaction, and focus management. Verify responsive behavior for the project's supported browser/viewport matrix.
