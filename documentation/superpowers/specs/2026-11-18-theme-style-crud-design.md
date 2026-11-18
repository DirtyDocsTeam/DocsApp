# Theme style CRUD

## Intent

Theme owners need to create, edit, and remove the styles nested in their themes.
The concrete schemas for `transform`, `render`, and `validation` styles are not
defined yet, so this change must not freeze a premature typed contract.

## Chosen approach

Expose GraphQL `createStyle`, `updateStyle`, and `deleteStyle` mutations. Their
`dataJson` argument is a JSON-encoded object and `type` remains the existing
`StyleType` enum. The API validates the object and exposes it unchanged as
`styleDescription.raw`. This uses the existing `styles` table and
`ThemeProjections.STYLE` read projection; no migration is required.

The alternatives were a temporary typed placeholder or separate typed input
models per style type. Both would introduce a public contract that will need a
breaking change once the actual schemas are known.

## Rules

- Only the direct owner (`themes.owner_user_id`) may mutate styles of the
  theme. Collection membership never grants this capability.
- API-token callers require `themes.edit` for create/update and
  `themes.delete` for delete. OIDC callers use the same ownership rule.
- `exampleText` must be non-blank; `data` must be a JSON object.
- Updates replace `type`, `exampleText`, and `data` atomically.
- Delete is physical: `styles` has no retention or soft-delete semantics and
  completed jobs retain their own persisted data.

## Verification

Add projection/authorization-focused unit tests, run the full unit suite, and
regenerate API documentation from the GraphQL annotations.
