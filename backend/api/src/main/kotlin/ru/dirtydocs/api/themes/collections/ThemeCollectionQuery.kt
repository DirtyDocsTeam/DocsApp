package ru.dirtydocs.api.themes.collections

import graphql.schema.DataFetchingEnvironment
import jakarta.enterprise.inject.Instance
import org.eclipse.microprofile.graphql.Description
import org.eclipse.microprofile.graphql.GraphQLApi
import org.eclipse.microprofile.graphql.Query
import org.jooq.DSLContext
import ru.dirtydocs.api.themes.ThemeProjections.THEME_COLLECTION
import ru.novari.data.ProjectionContext

@GraphQLApi
class ThemeCollectionQuery(
    private val contexts: Instance<ProjectionContext>,
    private val dsl: DSLContext,
) {
    @Query
    @Description("List personal theme collections")
    fun listPersonalThemes(env: DataFetchingEnvironment, limit: Int = 10, offset: Int = 0): List<ThemeCollection> {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
        // TODO: Implement "WHERE" filtration integration in projection API
        return projection.fetchPage(dsl, orderBy = listOf(), limit = limit, offset = offset)
    }
    @Query
    @Description("Search personal theme collections")
    fun searchPersonalThemes(env: DataFetchingEnvironment, query: String, limit: Int = 10, offset: Int = 0): List<ThemeCollection> {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
        // TODO: Implement "WHERE" filtration integration in projection API
        return projection.fetchPage(dsl, orderBy = listOf(), limit = limit, offset = offset)
    }

    @Query
    @Description("List theme collections")
    fun listThemes(env: DataFetchingEnvironment, limit: Int = 10, offset: Int = 0): List<ThemeCollection> {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
        return projection.fetchPage(dsl, orderBy = listOf(), limit = limit, offset = offset)
    }
    @Query
    @Description("Search theme collections")
    fun searchThemes(env: DataFetchingEnvironment, query: String, limit: Int = 10, offset: Int = 0): List<ThemeCollection> {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
        // TODO: Implement search integration in projection API
        return projection.fetchPage(dsl, orderBy = listOf(), limit = limit, offset = offset)
    }

    @Query
    @Description("Get theme collection by id")
    fun getTheme(env: DataFetchingEnvironment, id: Long): ThemeCollection? {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
        return projection.fetchById(dsl, id)
    }
    @Query
    @Description("Get theme collections by ids")
    fun getThemes(env: DataFetchingEnvironment, ids: List<Long>): List<ThemeCollection> {
        val context = contexts.get()
        val projection = THEME_COLLECTION.select(env, context)
        return projection.fetchByIds(dsl, ids)
    }
}