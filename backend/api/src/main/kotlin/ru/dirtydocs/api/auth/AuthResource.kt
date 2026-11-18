package ru.dirtydocs.api.auth

import io.quarkus.oidc.AuthorizationCodeFlow
import io.quarkus.oidc.OidcSession
import io.smallrye.mutiny.Uni
import jakarta.ws.rs.GET
import jakarta.ws.rs.POST
import jakarta.ws.rs.Path
import jakarta.ws.rs.Produces
import jakarta.ws.rs.core.MediaType
import jakarta.ws.rs.core.Response

/** Browser-only façade for the provider-managed OIDC registration and session lifecycle. */
@Path("/auth")
@Produces(MediaType.APPLICATION_JSON)
class AuthResource(
    private val session: OidcSession,
) {
    @GET
    @Path("/register")
    @AuthorizationCodeFlow
    fun register(): Response = Response.noContent().build()

    @GET
    @Path("/login")
    @AuthorizationCodeFlow
    fun login(): Response = Response.noContent().build()

    @POST
    @Path("/refresh")
    @AuthorizationCodeFlow
    fun refresh(): Response = Response.noContent().build()

    @POST
    @Path("/logout")
    @AuthorizationCodeFlow
    fun logout(): Uni<Response> = session.logout().replaceWith(Response.noContent().build())
}
