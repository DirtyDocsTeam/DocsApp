package ru.dirtydocs.api.themes

import org.jooq.SQLDialect
import org.jooq.impl.DSL
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import ru.dirtydocs.data.ProjectionContext
import ru.dirtydocs.data.Selection

class ThemeProjectionsTest {
    @Test
    fun anonymousViewerCannotMatchPersonalThemesOrCollections() {
        val context = ProjectionContext(viewerId = null)

        assertTrue(DSL.using(SQLDialect.POSTGRES).renderInlined(
            ThemeProjections.personalThemes(context),
        ).contains("false", ignoreCase = true))
        assertTrue(DSL.using(SQLDialect.POSTGRES).renderInlined(
            ThemeProjections.personalThemeCollections(context),
        ).contains("false", ignoreCase = true))
    }

    @Test
    fun blankThemeSearchDoesNotAddANameRestriction() {
        val sql = DSL.using(SQLDialect.POSTGRES).renderInlined(ThemeProjections.nameMatches("   "))

        assertFalse(sql.contains("name", ignoreCase = true))
    }

    @Test
    fun viewerAccessToThemesAndStylesUsesTheCollectionMembership() {
        val context = ProjectionContext(viewerId = 42)
        val dsl = DSL.using(SQLDialect.POSTGRES)

        val themeSql = dsl.renderInlined(ThemeProjections.THEME.compile(Selection.of("id"), context).condition)
        val styleSql = dsl.renderInlined(ThemeProjections.STYLE.compile(Selection.of("id"), context).condition)

        assertTrue(themeSql.contains("theme_collection_themes", ignoreCase = true))
        assertTrue(themeSql.contains("user_theme_collections", ignoreCase = true))
        assertTrue(themeSql.contains("42"))
        assertTrue(styleSql.contains("theme_id", ignoreCase = true))
        assertTrue(styleSql.contains("user_theme_collections", ignoreCase = true))
    }

    @Test
    fun collectionThemeRelationUsesTheManyToManyLinkTable() {
        val selection = Selection(mapOf("themes" to Selection.of("id")))
        val projection = ThemeProjections.THEME_COLLECTION.compile(
            selection,
            ProjectionContext(viewerId = 42),
        )
        val relationSql = DSL.using(SQLDialect.POSTGRES).renderInlined(projection.fields.last())

        assertTrue(relationSql.contains("theme_collection_themes", ignoreCase = true))
        assertTrue(relationSql.contains("theme_id", ignoreCase = true))
    }
}
