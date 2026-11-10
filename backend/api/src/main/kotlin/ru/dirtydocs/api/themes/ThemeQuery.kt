package ru.dirtydocs.api.themes

import graphql.schema.DataFetchingEnvironment
import jakarta.enterprise.inject.Instance
import org.eclipse.microprofile.graphql.Description
import org.eclipse.microprofile.graphql.GraphQLApi
import org.eclipse.microprofile.graphql.Query
import org.jooq.DSLContext
import ru.dirtydocs.api.themes.ThemeProjections.THEME
import ru.novari.data.ProjectionContext

@GraphQLApi
class ThemeQuery(
    private val contexts: Instance<ProjectionContext>,
    private val dsl: DSLContext,
) {
    @Query
    @Description("List personal themes")
    fun listPersonalThemes(env: DataFetchingEnvironment, limit: Int = 10, offset: Int = 0): List<Theme> {
        val context = contexts.get()
        val projection = THEME.select(env, context)
        // TODO: Implement "WHERE" filtration integration in projection API
        return projection.fetchPage(dsl, orderBy = listOf(), limit = limit, offset = offset)
    }
    @Query
    @Description("Search personal themes")
    fun searchPersonalThemes(env: DataFetchingEnvironment, query: String, limit: Int = 10, offset: Int = 0): List<Theme> {
        val context = contexts.get()
        val projection = THEME.select(env, context)
        // TODO: Implement "WHERE" filtration integration in projection API
        return projection.fetchPage(dsl, orderBy = listOf(), limit = limit, offset = offset)
    }

    @Query
    @Description("List themes")
    fun listThemes(env: DataFetchingEnvironment, limit: Int = 10, offset: Int = 0): List<Theme> {
        val context = contexts.get()
        val projection = THEME.select(env, context)
        return projection.fetchPage(dsl, orderBy = listOf(), limit = limit, offset = offset)
    }
    @Query
    @Description("Search themes")
    fun searchThemes(env: DataFetchingEnvironment, query: String, limit: Int = 10, offset: Int = 0): List<Theme> {
        val context = contexts.get()
        val projection = THEME.select(env, context)
        // TODO: Implement search integration in projection API
        return projection.fetchPage(dsl, orderBy = listOf(), limit = limit, offset = offset)
    }

    @Query
    @Description("Get theme by id")
    fun getTheme(env: DataFetchingEnvironment, id: Long): Theme? {
        val context = contexts.get()
        val projection = THEME.select(env, context)
        return projection.fetchById(dsl, id)
    }
    @Query
    @Description("Get themes by ids")
    fun getThemes(env: DataFetchingEnvironment, ids: List<Long>): List<Theme> {
        val context = contexts.get()
        val projection = THEME.select(env, context)
        return projection.fetchByIds(dsl, ids)
    }
}