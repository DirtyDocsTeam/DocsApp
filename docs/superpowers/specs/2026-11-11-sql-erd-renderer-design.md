# SQL ERD renderer and automatic layout — design

## Intent

Replace the current Mermaid-only generated ERD with a repository-local, deterministic
SVG renderer for the SQL schema. It should retain the concise table-card presentation
and relationship readability of `royalbhati/sqltoerdiagram`, without depending on its
website, a browser, npm packages, or a product frontend. The generated diagram must
make the DocsApp Liquibase schema easy to inspect in GitHub and the project wiki.

## Goals

- Generate `documentation/design/schema.svg` from the Liquibase-derived DDL alongside
  `db.sql` and the textual `erd.md`.
- Draw each table as a named card with column type/name/key metadata and draw foreign
  keys as routed connectors between card edges.
- Place cards without overlapping card rectangles and prefer layouts with neither
  connectors passing through cards nor connectors crossing each other.
- Make the output reproducible: the same DDL produces byte-stable SVG coordinates.
- Preserve `make db-schema`, `make db-erd`, and `make db-check` as the documented
  entry points; update their descriptions and the generated-documentation links.
- Cover DDL parsing, geometry/penalty calculations, overlap avoidance, and a small
  generated-schema regression fixture with focused Python tests.

## Non-goals

- No interactive browser editor, drag/drop, SQL input UI, pan/zoom UI, SQL sharing,
  or persistence of manual coordinates.
- No network request, headless browser, Docker dependency, or third-party Python
  dependency for rendering.
- No change to the Liquibase schema, backend API, or the user's unrelated local edit
  to `Projection.kt`.

## Approaches considered

1. **Local SVG renderer (chosen).** Extend `.github/scripts/db_schema.py` (or a small
   adjacent Python module) to construct table/card geometry and write SVG. This matches
   the existing standard-library-only documentation generator, works in CI, has fully
   controlled layout scoring, and keeps diffs reviewable.
2. **Browser version of `sqltoerdiagram`.** Embed or vendor its Vite/canvas app and
   capture an image. It would retain interactivity, but the repository has no frontend
   application to host it and it would introduce a JS build chain and browser runtime
   merely to generate a documentation artifact.
3. **Mermaid only.** Cheap and already present, but Mermaid owns node placement and
   cannot apply the requested weighted collision metrics.

## Design

### Artifacts and command behavior

`db_schema.py` continues to parse the Liquibase SQL once and builds three generated
artifacts:

- `documentation/design/db.sql` — unchanged purpose;
- `documentation/design/erd.md` — source-readable Mermaid plus FK table, retained as
  a text fallback;
- `documentation/design/schema.svg` — the new canonical rendered diagram.

Normal generation writes all stale artifacts. `--check` compares all three, exits
non-zero when any is stale, and reports which paths need regeneration. `--render` is
kept as a compatibility alias for generation rather than a network/browser operation.
`make db-erd` describes and invokes the SVG generation. Design documentation links
to the SVG preview and the Mermaid source.

### Visual model

Each parsed `Table` becomes a card whose width is calculated from the longest displayed
column and whose height is based on its rows. Cards have a distinct header and compact
rows; PK/FK markers and type/name hierarchy follow the reference renderer's legible
table-card idiom. Each FK is a cubic or orthogonal connector attached to the nearest
valid card edge, with an arrow at the referenced-table end and a small source-column
label only when it can be placed clear of cards.

The accepted visual reference uses a dark background, blue-grey card headers and rows,
alternating row fills, muted connector lines, yellow `PK` markers, and blue `FK`
markers. The generated SVG will use that same hierarchy and contrast (without copying
reference assets or application code) so it reads as the supplied example does at a
wide documentation-preview size.

The renderer computes a padded viewBox around all cards and paths, emits standard SVG
shapes/text, and escapes every DDL-derived label. It has no scripts or external assets.

### Automatic layout

The initial placement is a deterministic, hub-aware layered layout: the most connected
unplaced table starts a component; neighbours occupy the next layer; then remaining
components are placed with component spacing. Direction is left-to-right. The initial
grid pitch is larger than the largest card dimensions plus a fixed gutter, so cards do
not start overlapped.

A bounded deterministic local-search pass then tries legal moves of individual cards
over progressively smaller grid offsets. A separation pass moves any overlapping pair
apart before score evaluation. Candidate placements are accepted only if their score
improves, with a stable table-name tie-breaker and fixed iteration cap.

For a placement `P`, the optimizer minimizes:

```
score(P) =
  5.00 × FK-to-card intersections
  1.00 × FK-to-FK crossings
  0.10 × nearest-card gap
  0.01 × farthest-card gap
```

The last two terms implement the supplied negative-distance rewards equivalently: lower
scores favour both local compactness and avoiding isolated outliers. Gaps are the
non-negative rectangle-to-rectangle Euclidean gaps; intersecting cards are illegal and
are resolved by the separation pass rather than traded against a score. A connector's
intersection with either endpoint card is ignored, while intersections with every
other card count once. Crossing shared endpoints does not count as a line crossing.

The renderer exposes the individual score components in a pure layout result for tests
and prints a concise table/FK/score summary when generating. It avoids timestamps,
randomness, and iteration-order-dependent maps so regenerated SVG is stable.

### Failure handling and limits

If parsing produces no tables, generation fails with a clear message and leaves the
current artifacts untouched. Unknown or malformed relationship endpoints are rendered
as warnings and omitted from the SVG connector set, matching the current generator's
best-effort parsing stance. Layout has an explicit maximum candidate and iteration
budget; it returns the best non-overlapping placement found rather than looping
unboundedly.

## Validation

- Focused Python unit tests for segment/rectangle and segment/segment collision rules,
  endpoint exemptions, card separation, penalty ordering, and determinism.
- Run the generator twice and assert no artifact changes on the second run.
- Run `make db-check` and the focused test suite; run `make db-verify` when Docker is
  available.
- Visually inspect the generated SVG at the current 12-table/15-FK schema and confirm
  no card overlaps and no connector crosses a non-endpoint card.

## Builder decisions left intentionally open

- Exact colour palette, font family, padding, connector bend style, and SVG filename
  markup are implementation details, provided they remain readable, local, accessible
  in SVG text, and deterministic.
- The layout may split disconnected components into rows or columns if that reduces
  the stated score while preserving deterministic output.
