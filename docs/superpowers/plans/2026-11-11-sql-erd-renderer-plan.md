# SQL ERD renderer and automatic layout — implementation plan

## Scope

Implement the approved local SVG ERD renderer described in
`docs/superpowers/specs/2026-11-11-sql-erd-renderer-design.md`. It changes only the
documentation generator, its generated design artifacts, tests, and references.

## Steps

1. Extract pure ERD geometry and SVG rendering helpers from `.github/scripts/db_schema.py`
   into focused standard-library Python code. Model rectangles, points, connectors,
   positioned cards, layout score components, and render options with dataclasses.
2. Implement deterministic initial placement based on connected-component traversal and
   degree-ranked layers. Compute card dimensions from escaped display strings.
3. Implement a separation pass and bounded local search. Score placements using the
   approved 5/1/0.10/0.01 weights; exempt endpoint-card contact and shared-endpoint
   relationships as defined by the design.
4. Render the dark, table-card SVG: background, header, alternating rows, PK/FK accents,
   edge-attached connector paths, and a padded `viewBox`. Keep all SVG content local
   and escape SQL-derived text.
5. Make `db_schema.py` build/check `schema.svg`, retain `erd.md`, and support the
   existing `--render` spelling as a local compatibility alias. Update Makefile help
   and documentation pages to call the SVG artifact canonical while retaining Mermaid
   as source-readable fallback.
6. Add focused `unittest` coverage for geometry, score accounting, non-overlap,
   determinism, and the generated current schema. Regenerate committed artifacts.
7. Run focused tests, `make db-check`, and the generator twice for idempotency. Run the
   appropriate formatting/static check if one exists, visually inspect the SVG, then
   run the repository's code-review workflow and commit the scoped changes.

## Completion checks

- `make db-schema` generates byte-stable `documentation/design/schema.svg`.
- `make db-check` validates `db.sql`, `erd.md`, and `schema.svg`.
- The committed diagram has no table-card overlaps or FK lines through non-endpoint cards.
- Tests demonstrate the supplied score weights and collision rules.
