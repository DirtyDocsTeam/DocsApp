package ru.dirtydocs.api.themes.collections

import graphql.schema.DataFetchingEnvironment
import jakarta.enterprise.inject.Instance
import org.eclipse.microprofile.graphql.Description
import org.eclipse.microprofile.graphql.GraphQLApi
import org.eclipse.microprofile.graphql.Query
import org.jooq.DSLContext
import org.jooq.SortField
import ru.dirtydocs.api.themes.ThemeProjections
import ru.dirtydocs.api.themes.ThemeProjections.THEME_COLLECTION
import ru.dirtydocs.spectra.generated.jooq.tables.references.THEME_COLLECTIONS
import ru.dirtydocs.data.ProjectionContext

@GraphQLApi
class ThemeCollectionQuery(
    private val contexts: Instance<ProjectionContext>,
    private val dsl: DSLContext,
) {
    @Query
    @Description("List personal theme collections")
    fun listPersonalThemeCollections(env: DataFetchingEnvironment, limit: Int = 10, offset: Int = 0): List<ThemeCollection> {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
            .where(ThemeProjections.personalThemeCollections(context))
        return projection.fetchPage(dsl, orderBy = collectionOrder, limit = limit, offset = offset)
    }
    @Query
    @Description("Search personal theme collections")
    fun searchPersonalThemeCollections(env: DataFetchingEnvironment, query: String, limit: Int = 10, offset: Int = 0): List<ThemeCollection> {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
            .where(ThemeProjections.personalThemeCollections(context))
            .where(ThemeProjections.collectionNameMatches(query))
        return projection.fetchPage(dsl, orderBy = collectionOrder, limit = limit, offset = offset)
    }

    @Query
    @Description("List theme collections")
    fun listThemeCollections(env: DataFetchingEnvironment, limit: Int = 10, offset: Int = 0): List<ThemeCollection> {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
        return projection.fetchPage(dsl, orderBy = collectionOrder, limit = limit, offset = offset)
    }
    @Query
    @Description("Search theme collections")
    fun searchThemeCollections(env: DataFetchingEnvironment, query: String, limit: Int = 10, offset: Int = 0): List<ThemeCollection> {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
            .where(ThemeProjections.collectionNameMatches(query))
        return projection.fetchPage(dsl, orderBy = collectionOrder, limit = limit, offset = offset)
    }

    @Query
    @Description("Get theme collection by id")
    fun getThemeCollection(env: DataFetchingEnvironment, id: Long): ThemeCollection? {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
        return projection.fetchById(dsl, id)
    }
    @Query
    @Description("Get theme collections by ids")
    fun getThemeCollections(env: DataFetchingEnvironment, ids: List<Long>): List<ThemeCollection> {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
        return projection.fetchByIds(dsl, ids)
    }

    private companion object {
        val collectionOrder: List<SortField<*>> = listOf(
            THEME_COLLECTIONS.UPDATED_AT.desc(),
            THEME_COLLECTIONS.ID.desc(),
        )
    }
}
