package ru.dirtydocs.api.auth

import jakarta.enterprise.context.ApplicationScoped
import jakarta.enterprise.inject.Produces
import ru.dirtydocs.data.ProjectionContext

/**
 * Converts OIDC or api token into a [ProjectionContext].
 * Client-supplied GraphQL arguments never participate in this decision.
 */
@ApplicationScoped
class ProjectionContextProducer {
    @Produces
    fun projectionContext(): ProjectionContext {
        // TODO: replace with real identity
        return ProjectionContext(viewerId = 1)
    }
}
