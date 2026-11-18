package ru.dirtydocs.api.themes.styles

import graphql.schema.DataFetchingEnvironment
import jakarta.enterprise.inject.Instance
import jakarta.ws.rs.ClientErrorException
import jakarta.ws.rs.core.Response
import org.eclipse.microprofile.graphql.Description
import org.eclipse.microprofile.graphql.GraphQLApi
import org.eclipse.microprofile.graphql.Mutation
import org.jooq.DSLContext
import org.jooq.JSONB
import org.jooq.impl.DSL
import ru.dirtydocs.api.auth.ApiTokenAccessAuthorizer
import ru.dirtydocs.api.generated.jooq.tables.references.STYLES
import ru.dirtydocs.api.generated.jooq.tables.references.THEMES
import ru.dirtydocs.api.themes.ThemeProjections
import ru.dirtydocs.data.ProjectionContext
import java.time.OffsetDateTime

/** Direct theme-owner commands for the otherwise schema-agnostic style payload. */
@GraphQLApi
class StyleMutation(
    private val contexts: Instance<ProjectionContext>,
    private val dsl: DSLContext,
    private val tokenAccess: ApiTokenAccessAuthorizer,
) {
    @Mutation
    @Description("Create a style in a theme owned by the current user")
    fun createStyle(
        env: DataFetchingEnvironment,
        themeId: Long,
        type: StyleType,
        exampleText: String,
        dataJson: String,
    ): Style {
        tokenAccess.requireEdit { it.themes }
        requireOwnedTheme(themeId)
        val id = dsl.insertInto(STYLES)
            .set(STYLES.THEME_ID, themeId)
            .set(STYLES.TYPE, type.dbValue)
            .set(STYLES.EXAMPLE_TEXT, requiredExampleText(exampleText))
            .set(STYLES.DATA, JSONB.valueOf(StylePayload.requireJsonObject(dataJson)))
            .returning(STYLES.ID)
            .fetchOne(STYLES.ID)
            ?: error("Style creation did not return an id")
        return fetchStyle(env, id)
    }

    @Mutation
    @Description("Replace a style in a theme owned by the current user")
    fun updateStyle(
        env: DataFetchingEnvironment,
        id: Long,
        type: StyleType,
        exampleText: String,
        dataJson: String,
    ): Style {
        tokenAccess.requireEdit { it.themes }
        val updated = dsl.update(STYLES)
            .set(STYLES.TYPE, type.dbValue)
            .set(STYLES.EXAMPLE_TEXT, requiredExampleText(exampleText))
            .set(STYLES.DATA, JSONB.valueOf(StylePayload.requireJsonObject(dataJson)))
            .where(STYLES.ID.eq(id))
            .and(STYLES.THEME_ID.`in`(ownedThemeIds()))
            .execute()
        if (updated != 1) throw ClientErrorException(Response.Status.NOT_FOUND)
        return fetchStyle(env, id)
    }

    @Mutation
    @Description("Delete a style from a theme owned by the current user")
    fun deleteStyle(id: Long): Boolean {
        tokenAccess.requireDelete { it.themes }
        return dsl.deleteFrom(STYLES)
            .where(STYLES.ID.eq(id))
            .and(STYLES.THEME_ID.`in`(ownedThemeIds()))
            .execute() == 1
    }

    private fun fetchStyle(env: DataFetchingEnvironment, id: Long): Style =
        ThemeProjections.STYLE.select(env, contexts.get()).fetchById(dsl, id)
            ?: error("Owned style is not visible")

    private fun requireOwnedTheme(themeId: Long) {
        if (!dsl.fetchExists(DSL.selectOne().from(THEMES).where(THEMES.ID.eq(themeId).and(ownedThemeCondition())))) {
            throw ClientErrorException(Response.Status.NOT_FOUND)
        }
    }

    private fun ownedThemeIds() = DSL.select(THEMES.ID).from(THEMES).where(ownedThemeCondition())

    private fun ownedThemeCondition() = ownerId.eq(requireViewer()).and(deletedAt.isNull)

    private fun requireViewer(): Long = contexts.get().viewerId
        ?: throw ClientErrorException(Response.Status.UNAUTHORIZED)

    private fun requiredExampleText(value: String): String = value.trim().also { require(it.isNotEmpty()) }

    private companion object {
        val ownerId = DSL.field(DSL.name("themes", "owner_user_id"), Long::class.java)
        val deletedAt = DSL.field(DSL.name("themes", "deleted_at"), OffsetDateTime::class.java)
    }
}
