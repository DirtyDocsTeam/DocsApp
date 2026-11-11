package ru.dirtydocs.api.themes

import kotlinx.serialization.json.Json
import org.jooq.Condition
import org.jooq.impl.DSL
import ru.dirtydocs.api.themes.collections.ThemeCollection
import ru.dirtydocs.api.themes.collections.ThemeCollectionParameters
import ru.dirtydocs.api.themes.styles.Style
import ru.dirtydocs.api.themes.styles.StyleDescription
import ru.dirtydocs.data.ManyRelation
import ru.dirtydocs.data.Projection
import ru.dirtydocs.data.ProjectionContext
import ru.dirtydocs.data.columnNodes
import ru.dirtydocs.data.jsonb
import ru.dirtydocs.spectra.generated.jooq.tables.references.STYLES
import ru.dirtydocs.spectra.generated.jooq.tables.references.THEMES
import ru.dirtydocs.spectra.generated.jooq.tables.references.THEME_COLLECTIONS
import ru.dirtydocs.spectra.generated.jooq.tables.references.THEME_COLLECTION_THEMES
import ru.dirtydocs.spectra.generated.jooq.tables.references.USER_THEME_COLLECTIONS

object ThemeProjections {
    private val json = Json {
        ignoreUnknownKeys = true
        decodeEnumsCaseInsensitive = true
    }
    val STYLE: Projection<Style> = Projection(
        table = STYLES,
        id = STYLES.ID,
        nodes = columnNodes(
            mapOf(
                "id" to STYLES.ID,
                "type" to STYLES.TYPE,
                "exampleText" to STYLES.EXAMPLE_TEXT,
                "styleDescription" to jsonb(STYLES.DATA, StyleDescription.serializer(), json)
            )
        ),
        required = setOf("id"),
        factory = ::Style,
        access = ::styleAccess,
    )
    val THEME: Projection<Theme> = Projection(
        table = THEMES,
        id = THEMES.ID,
        nodes = columnNodes(
            mapOf(
                "id" to THEMES.ID,
                "name" to THEMES.NAME,
                "isPublic" to THEMES.IS_PUBLIC,
                "parameters" to jsonb(THEMES.PARAMETERS, ThemeParameters.serializer(), json),
                "createdAt" to THEMES.CREATED_AT,
                "updatedAt" to THEMES.UPDATED_AT
            )
        ) + mapOf(
            "styles" to ManyRelation(
                childProvider = { STYLE },
                relationCondition = { STYLES.THEME_ID.eq(THEMES.ID) },
                orderBy = { listOf(STYLES.ID.desc()) },
                defaultLimit = 10,
                maxLimit = 100
            )
        ),
        required = setOf("id"),
        factory = ::Theme,
        access = ::themeAccess,
    )
    val THEME_COLLECTION: Projection<ThemeCollection> = Projection(
        table = THEME_COLLECTIONS,
        id = THEME_COLLECTIONS.ID,
        nodes = columnNodes(
            mapOf(
                "id" to THEME_COLLECTIONS.ID,
                "name" to THEME_COLLECTIONS.NAME,
                "isPublic" to THEME_COLLECTIONS.IS_PUBLIC,
                "parameters" to jsonb(THEME_COLLECTIONS.PARAMETERS, ThemeCollectionParameters.serializer(), json),
                "createdAt" to THEME_COLLECTIONS.CREATED_AT,
                "updatedAt" to THEME_COLLECTIONS.UPDATED_AT
            )
        ) + mapOf(
            "themes" to ManyRelation(
                childProvider = { THEME },
                relationCondition = {
                    THEMES.ID.`in`(
                        DSL.select(THEME_COLLECTION_THEMES.THEME_ID)
                            .from(THEME_COLLECTION_THEMES)
                            .where(THEME_COLLECTION_THEMES.THEME_COLLECTION_ID.eq(THEME_COLLECTIONS.ID))
                    )
                },
                orderBy = { listOf(THEMES.ID.desc()) },
                defaultLimit = 10,
                maxLimit = 100
            )
        ),
        required = setOf("id"),
        factory = ::ThemeCollection,
        access = ::themeCollectionAccess,
    )

    /** Restricts themes to collections assigned to the trusted viewer; anonymous viewers match none. */
    internal fun personalThemes(context: ProjectionContext): Condition =
        context.viewerId?.let { viewerId ->
            THEMES.ID.`in`(
                DSL.select(THEME_COLLECTION_THEMES.THEME_ID)
                    .from(THEME_COLLECTION_THEMES)
                    .join(USER_THEME_COLLECTIONS)
                    .on(THEME_COLLECTION_THEMES.THEME_COLLECTION_ID.eq(USER_THEME_COLLECTIONS.THEME_COLLECTION_ID))
                    .where(USER_THEME_COLLECTIONS.USER_ID.eq(viewerId))
            )
        } ?: DSL.falseCondition()

    /** Restricts collections to those assigned to the trusted viewer; anonymous viewers match none. */
    internal fun personalThemeCollections(context: ProjectionContext): Condition =
        context.viewerId?.let { viewerId ->
            THEME_COLLECTIONS.ID.`in`(
                DSL.select(USER_THEME_COLLECTIONS.THEME_COLLECTION_ID)
                    .from(USER_THEME_COLLECTIONS)
                    .where(USER_THEME_COLLECTIONS.USER_ID.eq(viewerId))
            )
        } ?: DSL.falseCondition()

    internal fun nameMatches(query: String): Condition =
        query.takeIf(String::isNotBlank)?.let(THEMES.NAME::containsIgnoreCase)
            ?: DSL.trueCondition()

    internal fun collectionNameMatches(query: String): Condition =
        query.takeIf(String::isNotBlank)?.let(THEME_COLLECTIONS.NAME::containsIgnoreCase)
            ?: DSL.trueCondition()

    private fun themeAccess(context: ProjectionContext): Condition =
        THEMES.IS_PUBLIC.eq(true).or(personalThemes(context))

    private fun styleAccess(context: ProjectionContext): Condition =
        STYLES.THEME_ID.`in`(
            DSL.select(THEMES.ID)
                .from(THEMES)
                .where(themeAccess(context))
        )

    private fun themeCollectionAccess(context: ProjectionContext): Condition =
        THEME_COLLECTIONS.IS_PUBLIC.eq(true).or(personalThemeCollections(context))
}
