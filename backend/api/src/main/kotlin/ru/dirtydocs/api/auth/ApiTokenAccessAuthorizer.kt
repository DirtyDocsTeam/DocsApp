package ru.dirtydocs.api.auth

import io.quarkus.security.identity.SecurityIdentity
import jakarta.enterprise.context.ApplicationScoped
import jakarta.ws.rs.ForbiddenException
import ru.dirtydocs.api.users.tokens.access.AccessPermissions
import ru.dirtydocs.api.users.tokens.access.TokenAccessRights

/** Applies API-token scope restrictions while allowing OIDC and anonymous public-resource access. */
@ApplicationScoped
class ApiTokenAccessAuthorizer(
    private val identity: SecurityIdentity,
) {
    fun requireRead(scope: (TokenAccessRights) -> AccessPermissions) {
        val access = identity.getAttribute<TokenAccessRights>(ACCESS_ATTRIBUTE) ?: return
        if (!scope(access).read) throw ForbiddenException()
    }

    fun requireEdit(scope: (TokenAccessRights) -> AccessPermissions) {
        val access = identity.getAttribute<TokenAccessRights>(ACCESS_ATTRIBUTE) ?: return
        if (!scope(access).edit) throw ForbiddenException()
    }

    fun requireDelete(scope: (TokenAccessRights) -> AccessPermissions) {
        val access = identity.getAttribute<TokenAccessRights>(ACCESS_ATTRIBUTE) ?: return
        if (!scope(access).delete) throw ForbiddenException()
    }
}
