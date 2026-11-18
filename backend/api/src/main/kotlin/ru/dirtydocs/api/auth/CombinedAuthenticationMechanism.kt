package ru.dirtydocs.api.auth

import io.quarkus.oidc.runtime.OidcAuthenticationMechanism
import io.quarkus.security.identity.IdentityProviderManager
import io.quarkus.security.identity.SecurityIdentity
import io.quarkus.security.identity.request.AuthenticationRequest
import io.quarkus.vertx.http.runtime.security.ChallengeData
import io.quarkus.vertx.http.runtime.security.HttpAuthenticationMechanism
import io.quarkus.vertx.http.runtime.security.HttpCredentialTransport
import io.smallrye.mutiny.Uni
import io.vertx.ext.web.RoutingContext
import jakarta.annotation.Priority
import jakarta.enterprise.context.ApplicationScoped
import jakarta.enterprise.inject.Alternative

/** Routes opaque API tokens to the local provider and delegates every other request to OIDC. */
@Alternative
@Priority(1)
@ApplicationScoped
class CombinedAuthenticationMechanism(
    private val oidc: OidcAuthenticationMechanism,
) : HttpAuthenticationMechanism {
    override fun authenticate(
        context: RoutingContext,
        identityProviderManager: IdentityProviderManager,
    ): Uni<SecurityIdentity> {
        val value = bearerToken(context) ?: return oidc.authenticate(context, identityProviderManager)
        val credentials = ApiTokenCredentials.parse(value)
            ?: return oidc.authenticate(context, identityProviderManager)
        return identityProviderManager.authenticate(ApiTokenAuthenticationRequest(credentials))
    }

    override fun getChallenge(context: RoutingContext): Uni<ChallengeData> =
        if (bearerToken(context)?.let(ApiTokenCredentials::parse) != null) {
            Uni.createFrom().item(ChallengeData(401, "WWW-Authenticate", "Bearer"))
        } else {
            oidc.getChallenge(context)
        }

    override fun getCredentialTypes(): Set<Class<out AuthenticationRequest>> =
        oidc.credentialTypes + ApiTokenAuthenticationRequest::class.java

    override fun getCredentialTransport(context: RoutingContext): Uni<HttpCredentialTransport> =
        oidc.getCredentialTransport(context)

    private fun bearerToken(context: RoutingContext): String? =
        context.request().getHeader("Authorization")
            ?.takeIf { it.startsWith("Bearer ", ignoreCase = true) }
            ?.substringAfter(' ')
}
