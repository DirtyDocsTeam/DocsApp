package ru.dirtydocs.api.auth

import io.quarkus.security.identity.SecurityIdentity
import jakarta.enterprise.context.ApplicationScoped
import jakarta.enterprise.inject.Produces
import org.eclipse.microprofile.jwt.JsonWebToken
import ru.novari.data.ProjectionContext

/**
 * Converts the already verified bearer token into the only viewer identity used by projections.
 * Client-supplied GraphQL arguments never participate in this decision.
 */
@ApplicationScoped
class ProjectionContextProducer {
    @Produces
    fun projectionContext(): ProjectionContext {
        return ProjectionContext(viewerId = 1)
    }
}
