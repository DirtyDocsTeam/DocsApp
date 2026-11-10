# DocsApp: instructions for agents

Read [`PROJECT.md`](PROJECT.md) before planning a change. It describes the product scope, architectural direction, key constraints, and terminology.
Read [`coding-style.md`](coding-style.md) before changing code. Also read the applicable language guide from [`code-style/`](code-style/).

## Local agent resources

This repository may provide project-local agent resources. Use applicable resources from this directory before falling back to global resources:

1. Read [`harness/README.md`](harness/README.md) and use a listed harness when it covers the task.
2. Read [`skills/README.md`](skills/README.md) and follow a listed skill when it covers the task.
3. Read [`mcps/README.md`](mcps/README.md) and use a listed, available MCP integration when it covers the task.

Do not invent a harness, skill, or MCP integration that is absent from the relevant registry. If the task would materially benefit from a skill that is not available locally or globally, explicitly recommend installing it and name the capability it should provide. Do not install tools, skills, packages, or MCP servers without the user's approval.

The registries are deliberately extensible. When an owner supplies a list of resources, add each resource to its matching registry with its purpose, location or invocation method, prerequisites, and usage notes.

## Agent and harness compatibility

The canonical rules live exclusively in `.agents/`. Tool-specific instruction files are compatibility adapters and must only point here; do not duplicate, fork, or override project rules in them. See [`adapters.md`](adapters.md) for supported tools and setup notes.

## Working rules

- Treat this repository as an early-stage system: verify assumptions against the current code, database schema, and documentation before implementing a feature.
- Preserve product invariants in `PROJECT.md`, especially user-data isolation, retention, security, and asynchronous job lifecycle semantics.
- Apply the common code style and the applicable language-specific style. When they conflict with conventions already established in the touched module, preserve the local convention unless the task explicitly standardizes it.
- Keep backend, frontend, operations, and documentation changes in their respective top-level directories unless a cross-cutting change genuinely needs more than one area.
- Never place secrets, access tokens, user documents, generated production artifacts, or personally identifiable data in source control.
- For conversion or rendering changes, consider failure paths, idempotency, observability, safe cleanup, and user-facing errors in addition to the happy path.
- For schema changes, add migrations rather than editing a deployed schema in place; keep the reference schema and related documentation consistent when appropriate.
- Run focused checks available in the repository and report anything that could not be verified.
- C4 relationship directions come from arrowheads in `documentation/design/context.drawio`, not from the
  wording of an edge label: `A → B` means the arrowhead is drawn at `B`, so `gRPC [Announce]` is
  `Worker Pool → Main API Plane`. The connections table in `documentation/design/design.md` is generated from
  the diagram (`make c4-relations`) and verified in CI (`make c4-check`); read it instead of inferring
  direction from protocol names, and never edit the block by hand.
- API contracts (REST, GraphQL, gRPC) are generated from code, not written by hand: `make api-docs` renders
  `documentation/api/` by the rules in `api-docs.toml`, and the `docs → wiki` workflow publishes it. When an
  endpoint, schema, or `.proto` changes, update `api-docs.toml` or the source annotations instead of editing
  the generated pages, and run `make api-docs-check` locally.

## Source hierarchy

For product intent, use this precedence order:

1. The user's current request and accepted decisions.
2. Repository code, tests, and current architecture documentation.
3. [`PROJECT.md`](PROJECT.md), which is an initial product baseline synthesized from the supplied requirements and diagrams.

The baseline is context, not authorization to implement unrelated features. Ask for clarification if requirements conflict or materially affect security, data retention, or public API behavior.
