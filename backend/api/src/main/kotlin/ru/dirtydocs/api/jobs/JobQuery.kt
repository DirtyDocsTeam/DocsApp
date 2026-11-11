package ru.dirtydocs.api.jobs

import graphql.schema.DataFetchingEnvironment
import jakarta.enterprise.inject.Instance
import org.eclipse.microprofile.graphql.Description
import org.eclipse.microprofile.graphql.GraphQLApi
import org.eclipse.microprofile.graphql.Query
import org.jooq.DSLContext
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_REQUEST
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_RESULT
import ru.dirtydocs.api.jobs.JobProjections.REQUEST
import ru.dirtydocs.api.jobs.JobProjections.RESULT
import ru.dirtydocs.api.jobs.requests.JobRequest
import ru.dirtydocs.api.jobs.results.JobResult
import ru.dirtydocs.data.ProjectionContext

@GraphQLApi
class JobQuery(
    private val contexts: Instance<ProjectionContext>,
    private val dsl: DSLContext,
) {
    @Query
    @Description("List my jobs")
    fun myJobs(env: DataFetchingEnvironment, limit: Int = 10, offset: Int = 0): List<JobRequest> {
        val context = contexts.get()
        val projection = REQUEST.select(env, context)
        return projection.fetchPage(dsl, orderBy = listOf(JOB_REQUEST.CREATED_AT.desc(), JOB_REQUEST.ID.desc()), limit = limit, offset = offset)
    }
    @Query
    @Description("List my results")
    fun myResults(env: DataFetchingEnvironment, limit: Int = 10, offset: Int = 0): List<JobResult> {
        val context = contexts.get()
        val projection = RESULT.select(env, context)
        return projection.fetchPage(dsl, orderBy = listOf(JOB_RESULT.COMPLETED_AT.desc(), JOB_RESULT.ID.desc()), limit = limit, offset = offset)
    }
}
