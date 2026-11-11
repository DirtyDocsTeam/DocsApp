package ru.dirtydocs.api.users

import graphql.schema.DataFetchingEnvironment
import jakarta.enterprise.inject.Instance
import org.eclipse.microprofile.graphql.Description
import org.eclipse.microprofile.graphql.GraphQLApi
import org.eclipse.microprofile.graphql.Query
import org.jooq.DSLContext
import ru.dirtydocs.api.users.UserProjections.USER
import ru.dirtydocs.data.ProjectionContext

@GraphQLApi
class UserQuery(
    private val contexts: Instance<ProjectionContext>,
    private val dsl: DSLContext,
) {
    @Query
    @Description("Get current user")
    fun me(env: DataFetchingEnvironment): User? {
        val context = contexts.get()
        val viewerId = context.viewerId ?: return null
        val projection = USER.select(env, context)
        return projection.fetchById(dsl, viewerId)
    }
}