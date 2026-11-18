package ru.dirtydocs.api.subscriptions

import jakarta.enterprise.inject.Instance
import jakarta.ws.rs.ClientErrorException
import jakarta.ws.rs.core.Response
import io.smallrye.graphql.api.Subscription
import org.eclipse.microprofile.graphql.Description
import org.eclipse.microprofile.graphql.GraphQLApi
import org.reactivestreams.Publisher
import ru.dirtydocs.api.auth.ApiTokenAccessAuthorizer
import ru.dirtydocs.data.ProjectionContext

/** WebSocket subscription entry points; authorization is performed when the client subscribes. */
@GraphQLApi
class SubscriptionApi(
    private val contexts: Instance<ProjectionContext>,
    private val tokenAccess: ApiTokenAccessAuthorizer,
    private val events: DomainEventPublisher,
) {
    @Subscription
    @Description("Subscribe to a current user's job status changes")
    fun jobStatus(jobId: String): Publisher<JobStatusChange> {
        tokenAccess.requireRead { it.jobs }
        return events.jobChangesFor(requireViewer(), jobId)
    }

    @Subscription
    @Description("Subscribe to changes of visible themes")
    fun themeChanges(): Publisher<ThemeChange> {
        tokenAccess.requireRead { it.themes }
        return events.themeChangesFor(requireViewer())
    }

    private fun requireViewer(): Long = contexts.get().viewerId
        ?: throw ClientErrorException(Response.Status.UNAUTHORIZED)
}
