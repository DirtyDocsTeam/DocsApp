package ru.dirtydocs.api.media

import graphql.schema.DataFetchingEnvironment
import jakarta.enterprise.inject.Instance
import org.eclipse.microprofile.graphql.Description
import org.eclipse.microprofile.graphql.GraphQLApi
import org.eclipse.microprofile.graphql.Query
import org.jooq.DSLContext
import ru.dirtydocs.api.auth.ApiTokenAccessAuthorizer
import ru.dirtydocs.data.ProjectionContext

/** Reads media only through the caller's job or result ownership relation. */
@GraphQLApi
class MediaQuery(
    private val contexts: Instance<ProjectionContext>,
    private val dsl: DSLContext,
    private val tokenAccess: ApiTokenAccessAuthorizer,
) {
    @Query
    @Description("Get an input media artifact by id")
    fun jobMedia(env: DataFetchingEnvironment, id: Long): Media? {
        tokenAccess.requireRead { it.jobs }
        val context = contexts.get()
        return MediaProjections.JOB_MEDIA.select(env, context).fetchById(dsl, id)
    }

    @Query
    @Description("Get an output media artifact by id")
    fun resultMedia(env: DataFetchingEnvironment, id: Long): Media? {
        tokenAccess.requireRead { it.jobs }
        val context = contexts.get()
        return MediaProjections.RESULT_MEDIA.select(env, context).fetchById(dsl, id)
    }
}
