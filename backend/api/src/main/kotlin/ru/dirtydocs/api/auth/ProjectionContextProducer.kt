package ru.dirtydocs.api.auth

import jakarta.enterprise.context.ApplicationScoped
import jakarta.enterprise.context.RequestScoped
import jakarta.enterprise.inject.Produces
import io.quarkus.security.AuthenticationFailedException
import io.quarkus.security.identity.SecurityIdentity
import org.eclipse.microprofile.jwt.JsonWebToken
import org.jooq.DSLContext
import ru.dirtydocs.data.ProjectionContext
import ru.dirtydocs.api.generated.jooq.tables.references.USERS

/**
 * Converts OIDC or api token into a [ProjectionContext].
 * Client-supplied GraphQL arguments never participate in this decision.
 */
@ApplicationScoped
class ProjectionContextProducer(
    private val identity: SecurityIdentity,
    private val dsl: DSLContext,
) {
    @Produces
    @RequestScoped
    fun projectionContext(): ProjectionContext {
        identity.getAttribute<Long>(USER_ID_ATTRIBUTE)?.let { return ProjectionContext(viewerId = it) }
        if (identity.isAnonymous) return ProjectionContext(viewerId = null)

        val token = identity.principal as? JsonWebToken ?: throw AuthenticationFailedException()
        val subject = token.subject ?: throw AuthenticationFailedException()
        val email = token.getClaim<String>("email") ?: throw AuthenticationFailedException()
        val viewerId = dsl.insertInto(USERS)
            .set(USERS.OIDC_TOKEN, subject)
            .set(USERS.EMAIL, email)
            .onConflict(USERS.OIDC_TOKEN)
            .doUpdate()
            .set(USERS.EMAIL, email)
            .returning(USERS.ID)
            .fetchOne(USERS.ID)
            ?: throw IllegalStateException("OIDC user registration did not return an id")
        return ProjectionContext(viewerId = viewerId)
    }
}
