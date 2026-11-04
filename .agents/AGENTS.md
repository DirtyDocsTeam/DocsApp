# DocsApp: instructions for agents

Read [`PROJECT.md`](PROJECT.md) before planning a change. It describes the product scope, architectural direction, key constraints, and terminology.

## Local agent resources

This repository may provide project-local agent resources. Use applicable resources from this directory before falling back to global resources:

1. Read [`harness/README.md`](harness/README.md) and use a listed harness when it covers the task.
2. Read [`skills/README.md`](skills/README.md) and follow a listed skill when it covers the task.
3. Read [`mcps/README.md`](mcps/README.md) and use a listed, available MCP integration when it covers the task.

Do not invent a harness, skill, or MCP integration that is absent from the relevant registry. If the task would materially benefit from a skill that is not available locally or globally, explicitly recommend installing it and name the capability it should provide. Do not install tools, skills, packages, or MCP servers without the user's approval.

The registries are deliberately extensible. When an owner supplies a list of resources, add each resource to its matching registry with its purpose, location or invocation method, prerequisites, and usage notes.

## Working rules

- Treat this repository as an early-stage system: verify assumptions against the current code, database schema, and documentation before implementing a feature.
- Preserve product invariants in `PROJECT.md`, especially user-data isolation, retention, security, and asynchronous job lifecycle semantics.
- Keep backend, frontend, operations, and documentation changes in their respective top-level directories unless a cross-cutting change genuinely needs more than one area.
- Never place secrets, access tokens, user documents, generated production artifacts, or personally identifiable data in source control.
- For conversion or rendering changes, consider failure paths, idempotency, observability, safe cleanup, and user-facing errors in addition to the happy path.
- For schema changes, add migrations rather than editing a deployed schema in place; keep the reference schema and related documentation consistent when appropriate.
- Run focused checks available in the repository and report anything that could not be verified.

## Source hierarchy

For product intent, use this precedence order:

1. The user's current request and accepted decisions.
2. Repository code, tests, and current architecture documentation.
3. [`PROJECT.md`](PROJECT.md), which is an initial product baseline synthesized from the supplied requirements and diagrams.

The baseline is context, not authorization to implement unrelated features. Ask for clarification if requirements conflict or materially affect security, data retention, or public API behavior.
