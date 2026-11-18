package ru.dirtydocs.api.auth

import io.quarkus.security.identity.request.AuthenticationRequest

class ApiTokenAuthenticationRequest(
    val credentials: ApiTokenCredentials,
) : AuthenticationRequest {
    private val attributes = mutableMapOf<String, Any>()

    @Suppress("UNCHECKED_CAST")
    override fun <T> getAttribute(name: String): T? = attributes[name] as? T

    override fun setAttribute(name: String, value: Any) {
        attributes[name] = value
    }

    override fun getAttributes(): Map<String, Any> = attributes
}
