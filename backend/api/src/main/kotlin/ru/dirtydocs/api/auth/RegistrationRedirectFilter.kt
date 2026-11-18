package ru.dirtydocs.api.auth

import io.quarkus.oidc.OidcRedirectFilter
import jakarta.enterprise.context.ApplicationScoped

/** Adds Keycloak's registration action only when the browser explicitly requests registration. */
@ApplicationScoped
class RegistrationRedirectFilter : OidcRedirectFilter {
    override fun filter(context: OidcRedirectFilter.OidcRedirectContext) {
        if (context.routingContext().request().path() == "/auth/register") {
            context.additionalQueryParams().add("kc_action", "register")
        }
    }
}
