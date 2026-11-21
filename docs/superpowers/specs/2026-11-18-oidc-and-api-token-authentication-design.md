# OIDC and API-token authentication

## Intent

Authenticate browser users with the existing Quarkus OIDC code flow and API clients with revocable opaque API tokens. The public service registers a verified OIDC user automatically on first use.

## Design

- The `Authorization: Bearer` header is routed by token format. A complete `ddat_<token-id>_<secret>` value is an API token; all other bearer values are delegated to Quarkus OIDC.
- OIDC failures never fall through to API-token verification. This prevents an expired or forged JWT from being treated as a different credential type.
- API tokens are looked up by their embedded identifier, checked against the stored bcrypt hash and expiry, and become a `SecurityIdentity` carrying the user id and granted access rights.
- API-token reads require the matching existing access scope (`userData.read`, `themes.read`, or `jobs.read`); OIDC and anonymous access keep their existing semantics.
- A verified OIDC principal must contain both `sub` and `email`. Its user row is inserted or updated atomically by `sub` on first request.
- Projection contexts derive the viewer id from the trusted security identity. Anonymous requests continue to have no viewer id, preserving public-resource access.

## Non-goals

- API-token creation, rotation, and revocation endpoints are not part of this change.
