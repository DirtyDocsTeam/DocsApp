package ru.dirtydocs.api.themes.collections

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
import ru.dirtydocs.api.generated.jooq.tables.references.THEME_COLLECTION_THEMES
import ru.dirtydocs.api.generated.jooq.tables.references.USER_THEME_COLLECTIONS
import ru.dirtydocs.api.subscriptions.DomainEventPublisher
import ru.dirtydocs.api.subscriptions.ThemeChange
import ru.dirtydocs.api.subscriptions.ThemeChangeAction
import ru.dirtydocs.api.themes.Theme
import ru.dirtydocs.api.themes.ThemeParameters
import ru.dirtydocs.api.themes.ThemeProjections
import ru.dirtydocs.data.ProjectionContext
import java.time.OffsetDateTime

/** Commands that manage collection membership without transferring theme ownership. */
@GraphQLApi
class ThemeCollectionMutation(
    private val contexts: Instance<ProjectionContext>,
    private val dsl: DSLContext,
    private val tokenAccess: ApiTokenAccessAuthorizer,
    private val events: DomainEventPublisher,
) {
    @Mutation
    @Description("Add a theme when the collection and theme owner both have administrative collection access")
    fun addThemeToCollection(collectionId: Long, themeId: Long): Boolean {
        tokenAccess.requireEdit { it.themes }
        requireCollectionAdministrator(collectionId)
        if (!themeOwnerIsCollectionAdministrator(collectionId, themeId)) {
            throw ClientErrorException(Response.Status.NOT_FOUND)
        }
        dsl.insertInto(THEME_COLLECTION_THEMES)
            .set(THEME_COLLECTION_THEMES.THEME_COLLECTION_ID, collectionId)
            .set(THEME_COLLECTION_THEMES.THEME_ID, themeId)
            .onConflictDoNothing()
            .execute()
        return true
    }

    @Mutation
    @Description("Detach a theme as the collection owner or the theme's direct owner")
    fun removeThemeFromCollection(collectionId: Long, themeId: Long): Boolean {
        tokenAccess.requireDelete { it.themes }
        val viewerId = requireViewer()
        return dsl.deleteFrom(THEME_COLLECTION_THEMES)
            .where(THEME_COLLECTION_THEMES.THEME_COLLECTION_ID.eq(collectionId))
            .and(THEME_COLLECTION_THEMES.THEME_ID.eq(themeId))
            .and(collectionOwnerCondition(collectionId, viewerId).or(themeOwnerCondition(themeId, viewerId)))
            .execute() == 1
    }

    @Mutation
    @Description("Detach the current owner's theme from a collection without deleting the theme")
    fun leaveThemeCollection(collectionId: Long, themeId: Long): Boolean {
        tokenAccess.requireEdit { it.themes }
        val viewerId = requireViewer()
        return dsl.deleteFrom(THEME_COLLECTION_THEMES)
            .where(THEME_COLLECTION_THEMES.THEME_COLLECTION_ID.eq(collectionId))
            .and(THEME_COLLECTION_THEMES.THEME_ID.eq(themeId))
            .and(themeOwnerCondition(themeId, viewerId))
            .execute() == 1
    }

    @Mutation
    @Description("Create a theme owned by the current user and link it to an administrable collection")
    fun createThemeInCollection(
        env: DataFetchingEnvironment,
        collectionId: Long,
        name: String,
        isPublic: Boolean,
        parameters: ThemeParameters,
    ): Theme {
        tokenAccess.requireEdit { it.themes }
        val viewerId = requireViewer()
        requireCollectionAdministrator(collectionId)
        val id = dsl.transactionResult { configuration ->
            val tx = DSL.using(configuration)
            val themeId = tx.insertInto(THEMES)
                .set(THEMES.NAME, name.trim().also { require(it.isNotEmpty()) })
                .set(THEMES.IS_PUBLIC, isPublic)
                .set(THEMES.PARAMETERS, JSONB.valueOf(json.encodeToString(parameters)))
                .set(ownerId, viewerId)
                .returning(THEMES.ID)
                .fetchOne(THEMES.ID)
                ?: error("Theme creation did not return an id")
            tx.insertInto(THEME_COLLECTION_THEMES)
                .set(THEME_COLLECTION_THEMES.THEME_COLLECTION_ID, collectionId)
                .set(THEME_COLLECTION_THEMES.THEME_ID, themeId)
                .execute()
            themeId
        }
        val theme = ThemeProjections.THEME.select(env, contexts.get()).fetchById(dsl, id)
            ?: error("Created theme is not visible to its owner")
        events.publishTheme(viewerId, theme.isPublic, ThemeChange(id, ThemeChangeAction.CREATED, OffsetDateTime.now()))
        return theme
    }

    private fun requireCollectionAdministrator(collectionId: Long) {
        if (!dsl.fetchExists(DSL.selectOne().from(USER_THEME_COLLECTIONS).where(collectionAdministratorCondition(collectionId, requireViewer())))) {
            throw ClientErrorException(Response.Status.NOT_FOUND)
        }
    }

    private fun themeOwnerIsCollectionAdministrator(collectionId: Long, themeId: Long): Boolean =
        dsl.fetchExists(
            DSL.selectOne()
                .from(THEMES)
                .join(USER_THEME_COLLECTIONS).on(USER_THEME_COLLECTIONS.USER_ID.eq(ownerId))
                .where(THEMES.ID.eq(themeId))
                .and(deletedAt.isNull)
                .and(USER_THEME_COLLECTIONS.THEME_COLLECTION_ID.eq(collectionId))
                .and(USER_THEME_COLLECTIONS.ROLE.`in`(administratorRoles)),
        )

    private fun collectionOwnerCondition(collectionId: Long, viewerId: Long) = DSL.exists(
        DSL.selectOne().from(USER_THEME_COLLECTIONS)
            .where(USER_THEME_COLLECTIONS.THEME_COLLECTION_ID.eq(collectionId))
            .and(USER_THEME_COLLECTIONS.USER_ID.eq(viewerId))
            .and(USER_THEME_COLLECTIONS.ROLE.eq(ThemeCollectionRole.OWNER.dbValue)),
    )

    private fun themeOwnerCondition(themeId: Long, viewerId: Long) = DSL.exists(
        DSL.selectOne().from(THEMES)
            .where(THEMES.ID.eq(themeId))
            .and(ownerId.eq(viewerId))
            .and(deletedAt.isNull),
    )

    private fun collectionAdministratorCondition(collectionId: Long, viewerId: Long) =
        USER_THEME_COLLECTIONS.THEME_COLLECTION_ID.eq(collectionId)
            .and(USER_THEME_COLLECTIONS.USER_ID.eq(viewerId))
            .and(USER_THEME_COLLECTIONS.ROLE.`in`(administratorRoles))

    private fun requireViewer(): Long = contexts.get().viewerId
        ?: throw ClientErrorException(Response.Status.UNAUTHORIZED)

    private companion object {
        val json = Json { ignoreUnknownKeys = true }
        val ownerId = DSL.field(DSL.name("themes", "owner_user_id"), Long::class.java)
        val deletedAt = DSL.field(DSL.name("themes", "deleted_at"), OffsetDateTime::class.java)
        val administratorRoles = listOf(ThemeCollectionRole.ADMIN.dbValue, ThemeCollectionRole.OWNER.dbValue)
    }
}
