# Theme collection membership commands

## Intent

Collections control which themes they contain without acquiring ownership of
those themes. A direct theme owner retains final control over their own theme.

## Chosen commands

- `removeThemeFromCollection(collectionId, themeId)` detaches a theme without
  deleting it. It is allowed to the collection `OWNER`, or to the direct owner
  when detaching their own theme.
- `addThemeToCollection(collectionId, themeId)` is allowed to a collection
  `ADMIN` or `OWNER`, only when the direct owner of the theme is also an
  `ADMIN` or `OWNER` of that collection.
- `leaveThemeCollection(collectionId, themeId)` is an explicit owner-only
  convenience mutation for detaching the owner's theme from a collection.
- `createThemeInCollection(collectionId, name, isPublic, parameters)` is
  allowed to a collection `ADMIN` or `OWNER`; it creates a theme owned by the
  caller and atomically links it to the collection.

## Invariants

- No collection command calls `deleteTheme`; deleting a theme remains a
  direct-owner action.
- Membership writes are idempotent where feasible: adding an existing link
  succeeds without duplication, while removing an absent link returns false.
- API-token callers need `themes.edit` for add/create/leave and
  `themes.delete` for removal. OIDC callers use the same role checks.
- All links are modified inside a database transaction where creation and
  linkage must succeed together.

## Verification

Add SQL/projection-oriented authorization tests, run the full unit suite, and
regenerate GraphQL documentation.
