package ru.dirtydocs.api.themes

import kotlinx.serialization.json.Json
import org.jooq.impl.DSL
import ru.dirtydocs.api.themes.collections.ThemeCollection
import ru.dirtydocs.api.themes.collections.ThemeCollectionParameters
import ru.dirtydocs.api.themes.styles.Style
import ru.dirtydocs.api.themes.styles.StyleDescription
import ru.novari.data.ManyRelation
import ru.novari.data.Projection
import ru.novari.data.columnNodes
import ru.novari.data.jsonb
import ru.novari.spectra.generated.jooq.tables.references.STYLES
import ru.novari.spectra.generated.jooq.tables.references.THEMES
import ru.novari.spectra.generated.jooq.tables.references.THEME_COLLECTIONS
import ru.novari.spectra.generated.jooq.tables.references.THEME_COLLECTION_THEMES
import ru.novari.spectra.generated.jooq.tables.references.USER_THEME_COLLECTIONS

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
        access = { context ->
            // TODO: Style by theme access rules if needed
            DSL.trueCondition()
        }
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
                childForeignKey = { STYLES.THEME_ID },
                parentKey = STYLES.ID,
                orderBy = { listOf(STYLES.ID.desc()) },
                defaultLimit = 10,
                maxLimit = 100
            )
        ),
        required = setOf("id"),
        factory = ::Theme,
        access = { context ->
            THEMES.IS_PUBLIC.eq(true).or(
                // TODO: Theme collection access rules
                DSL.trueCondition()
            )
        }
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
                childForeignKey = { THEME_COLLECTION_THEMES.THEME_COLLECTION_ID },
                parentKey = THEME_COLLECTIONS.ID,
                orderBy = { listOf(THEMES.ID.desc()) },
                defaultLimit = 10,
                maxLimit = 100
            )
        ),
        required = setOf("id"),
        factory = ::ThemeCollection,
        access = { context ->
            THEME_COLLECTIONS.IS_PUBLIC.eq(true).or(
                context.viewerId?.let { viewerId ->
                    THEME_COLLECTIONS.ID.`in`(
                        DSL.select(USER_THEME_COLLECTIONS.THEME_COLLECTION_ID)
                            .from(USER_THEME_COLLECTIONS)
                            .where(USER_THEME_COLLECTIONS.USER_ID.eq(viewerId))
                    )
                } ?: DSL.falseCondition()
            )
        }
    )
}