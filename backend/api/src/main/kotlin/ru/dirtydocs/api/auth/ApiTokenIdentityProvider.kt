package ru.dirtydocs.api.auth

import io.quarkus.security.AuthenticationFailedException
import io.quarkus.security.identity.AuthenticationRequestContext
import io.quarkus.security.identity.IdentityProvider
import io.quarkus.security.identity.SecurityIdentity
import io.quarkus.security.runtime.QuarkusSecurityIdentity
import io.smallrye.mutiny.Uni
import jakarta.enterprise.context.ApplicationScoped
import org.jooq.DSLContext
import org.mindrot.jbcrypt.BCrypt
import ru.dirtydocs.api.generated.jooq.tables.references.API_TOKENS
import ru.dirtydocs.api.users.tokens.access.TokenAccessRights
import java.security.Principal
import java.time.OffsetDateTime
import kotlinx.serialization.json.Json

/** Verifies revocable, opaque API tokens without exposing their secret in the resulting identity. */
@ApplicationScoped
class ApiTokenIdentityProvider(
    private val dsl: DSLContext,
) : IdentityProvider<ApiTokenAuthenticationRequest> {
    override fun getRequestType(): Class<ApiTokenAuthenticationRequest> = ApiTokenAuthenticationRequest::class.java

    override fun authenticate(
        request: ApiTokenAuthenticationRequest,
        context: AuthenticationRequestContext,
    ): Uni<SecurityIdentity> = context.runBlocking {
        val record = dsl.select(
            API_TOKENS.USER_ID,
            API_TOKENS.TOKEN_HASH,
            API_TOKENS.EXPIRES_AT,
            API_TOKENS.ACCESS,
        ).from(API_TOKENS)
            .where(API_TOKENS.ID.eq(request.credentials.id))
            .fetchOne()
            ?: throw AuthenticationFailedException()

        val expiresAt = record.get(API_TOKENS.EXPIRES_AT)
        val hash = record.get(API_TOKENS.TOKEN_HASH)
        if (expiresAt == null || !expiresAt.isAfter(OffsetDateTime.now()) || hash == null || !matches(request, hash)) {
            throw AuthenticationFailedException()
        }

        val userId = requireNotNull(record.get(API_TOKENS.USER_ID))
        val access = requireNotNull(record.get(API_TOKENS.ACCESS)).let {
            json.decodeFromString(TokenAccessRights.serializer(), it.data())
        }
        QuarkusSecurityIdentity.builder()
            .setPrincipal(Principal { "api-token:$userId" })
            .addAttribute(USER_ID_ATTRIBUTE, userId)
            .addAttribute(ACCESS_ATTRIBUTE, access)
            .build()
    }

    private fun matches(request: ApiTokenAuthenticationRequest, hash: String): Boolean =
        try {
            BCrypt.checkpw(request.credentials.secret, hash)
        } catch (_: IllegalArgumentException) {
            false
        }

    private companion object {
        val json = Json { ignoreUnknownKeys = true }
    }
}
