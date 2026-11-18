package ru.dirtydocs.api.themes

import graphql.schema.DataFetchingEnvironment
import jakarta.enterprise.inject.Instance
import jakarta.ws.rs.ClientErrorException
import jakarta.ws.rs.core.Response
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.eclipse.microprofile.graphql.Description
import org.eclipse.microprofile.graphql.GraphQLApi
import org.eclipse.microprofile.graphql.Mutation
import org.jooq.DSLContext
import org.jooq.JSONB
import org.jooq.impl.DSL
import ru.dirtydocs.api.auth.ApiTokenAccessAuthorizer
import ru.dirtydocs.api.generated.jooq.tables.references.THEMES
import ru.dirtydocs.api.subscriptions.DomainEventPublisher
import ru.dirtydocs.api.subscriptions.ThemeChange
import ru.dirtydocs.api.subscriptions.ThemeChangeAction
import ru.dirtydocs.api.themes.ThemeProjections.THEME
import ru.dirtydocs.data.ProjectionContext
import java.time.OffsetDateTime

/** Owner-authorized theme commands. Updates require the version observed by the caller. */
@GraphQLApi
class ThemeMutation(
    private val contexts: Instance<ProjectionContext>,
    private val dsl: DSLContext,
    private val tokenAccess: ApiTokenAccessAuthorizer,
    private val events: DomainEventPublisher,
) {
    @Mutation
    @Description("Create a theme owned by the current user")
    fun createTheme(
        env: DataFetchingEnvironment,
        name: String,
        isPublic: Boolean,
        parameters: ThemeParameters,
    ): Theme {
        tokenAccess.requireEdit { it.themes }
        val viewerId = requireViewer()
        val id = dsl.insertInto(THEMES)
            .set(THEMES.NAME, name.trim().also { require(it.isNotEmpty()) })
            .set(THEMES.IS_PUBLIC, isPublic)
            .set(THEMES.PARAMETERS, JSONB.valueOf(json.encodeToString(parameters)))
            .set(ownerId, viewerId)
            .returning(THEMES.ID)
            .fetchOne(THEMES.ID)
            ?: error("Theme creation did not return an id")
        val theme = THEME.select(env, contexts.get()).fetchById(dsl, id)
            ?: error("Created theme is not visible to its owner")
        events.publishTheme(viewerId, theme.isPublic, ThemeChange(id, ThemeChangeAction.CREATED, OffsetDateTime.now()))
        return theme
    }

    @Mutation
    @Description("Update an owned theme when its version matches")
    fun updateTheme(
        env: DataFetchingEnvironment,
        id: Long,
        expectedUpdatedAt: OffsetDateTime,
        name: String,
        isPublic: Boolean,
        parameters: ThemeParameters,
    ): Theme {
        tokenAccess.requireEdit { it.themes }
        val updated = dsl.update(THEMES)
            .set(THEMES.NAME, name.trim().also { require(it.isNotEmpty()) })
            .set(THEMES.IS_PUBLIC, isPublic)
            .set(THEMES.PARAMETERS, JSONB.valueOf(json.encodeToString(parameters)))
            .where(THEMES.ID.eq(id))
            .and(ownerId.eq(requireViewer()))
            .and(THEMES.UPDATED_AT.eq(expectedUpdatedAt))
            .and(deletedAt.isNull)
            .execute()
        if (updated != 1) throw ClientErrorException(Response.Status.CONFLICT)
        val theme = THEME.select(env, contexts.get()).fetchById(dsl, id)
            ?: error("Updated theme is not visible to its owner")
        events.publishTheme(requireViewer(), theme.isPublic, ThemeChange(id, ThemeChangeAction.UPDATED, OffsetDateTime.now()))
        return theme
    }

    @Mutation
    @Description("Logically delete an owned theme")
    fun deleteTheme(id: Long): Boolean {
        tokenAccess.requireDelete { it.themes }
        val viewerId = requireViewer()
        val isPublic = dsl.select(THEMES.IS_PUBLIC)
            .from(THEMES)
            .where(THEMES.ID.eq(id).and(ownerId.eq(viewerId)).and(deletedAt.isNull))
            .fetchOne(THEMES.IS_PUBLIC)
            ?: return false
        val deleted = dsl.update(THEMES)
            .set(deletedAt, OffsetDateTime.now())
            .where(THEMES.ID.eq(id))
            .and(ownerId.eq(viewerId))
            .and(deletedAt.isNull)
            .execute() == 1
        if (deleted) events.publishTheme(viewerId, isPublic, ThemeChange(id, ThemeChangeAction.DELETED, OffsetDateTime.now()))
        return deleted
    }

    private fun requireViewer(): Long = contexts.get().viewerId
        ?: throw ClientErrorException(Response.Status.UNAUTHORIZED)

    private companion object {
        val json = Json { ignoreUnknownKeys = true }
        val ownerId = DSL.field(DSL.name("themes", "owner_user_id"), Long::class.java)
        val deletedAt = DSL.field(DSL.name("themes", "deleted_at"), OffsetDateTime::class.java)
    }
}
