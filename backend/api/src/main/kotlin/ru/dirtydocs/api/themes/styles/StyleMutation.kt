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
import ru.dirtydocs.api.generated.jooq.tables.references.THEME_COLLECTION_THEMES
import ru.dirtydocs.api.generated.jooq.tables.references.USER_THEME_COLLECTIONS
import ru.dirtydocs.api.themes.ThemeProjections
import ru.dirtydocs.api.themes.collections.ThemeCollectionRole
import ru.dirtydocs.data.ProjectionContext
import java.time.OffsetDateTime

/** Theme-owner and collection-editor commands for the schema-agnostic style payload. */
@GraphQLApi
class StyleMutation(
    private val contexts: Instance<ProjectionContext>,
    private val dsl: DSLContext,
    private val tokenAccess: ApiTokenAccessAuthorizer,
) {
    @Mutation
    @Description("Create a style in an editable theme")
    fun createStyle(
        env: DataFetchingEnvironment,
        themeId: Long,
        type: StyleType,
        exampleText: String,
        dataJson: String,
    ): Style {
        tokenAccess.requireEdit { it.themes }
        requireEditableTheme(themeId)
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
    @Description("Replace a style in an editable theme")
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
            .and(STYLES.THEME_ID.`in`(editableThemeIds()))
            .execute()
        if (updated != 1) throw ClientErrorException(Response.Status.NOT_FOUND)
        return fetchStyle(env, id)
    }

    @Mutation
    @Description("Delete a style from an editable theme")
    fun deleteStyle(id: Long): Boolean {
        tokenAccess.requireDelete { it.themes }
        return dsl.deleteFrom(STYLES)
            .where(STYLES.ID.eq(id))
            .and(STYLES.THEME_ID.`in`(editableThemeIds()))
            .execute() == 1
    }

    private fun fetchStyle(env: DataFetchingEnvironment, id: Long): Style =
        ThemeProjections.STYLE.select(env, contexts.get()).fetchById(dsl, id)
            ?: error("Editable style is not visible")

    private fun requireEditableTheme(themeId: Long) {
        if (!dsl.fetchExists(DSL.selectOne().from(THEMES).where(THEMES.ID.eq(themeId).and(editableThemeCondition())))) {
            throw ClientErrorException(Response.Status.NOT_FOUND)
        }
    }

    private fun editableThemeIds() = DSL.select(THEMES.ID).from(THEMES).where(editableThemeCondition())

    private fun editableThemeCondition() = deletedAt.isNull.and(
        ownerId.eq(requireViewer()).or(
            THEMES.ID.`in`(
                DSL.select(THEME_COLLECTION_THEMES.THEME_ID)
                    .from(THEME_COLLECTION_THEMES)
                    .join(USER_THEME_COLLECTIONS)
                    .on(THEME_COLLECTION_THEMES.THEME_COLLECTION_ID.eq(USER_THEME_COLLECTIONS.THEME_COLLECTION_ID))
                    .where(USER_THEME_COLLECTIONS.USER_ID.eq(requireViewer()))
                    .and(USER_THEME_COLLECTIONS.ROLE.`in`(editorRoles)),
            )
        )
    )

    private fun requireViewer(): Long = contexts.get().viewerId
        ?: throw ClientErrorException(Response.Status.UNAUTHORIZED)

    private fun requiredExampleText(value: String): String = value.trim().also { require(it.isNotEmpty()) }

    private companion object {
        val deletedAt = DSL.field(DSL.name("themes", "deleted_at"), OffsetDateTime::class.java)
        val ownerId = DSL.field(DSL.name("themes", "owner_user_id"), Long::class.java)
        val editorRoles = listOf(
            ThemeCollectionRole.EDITOR.dbValue,
            ThemeCollectionRole.ADMIN.dbValue,
            ThemeCollectionRole.OWNER.dbValue,
        )
    }
}
