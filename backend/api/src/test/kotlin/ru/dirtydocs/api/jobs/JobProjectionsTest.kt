package ru.dirtydocs.api.jobs

import org.jooq.SQLDialect
import org.jooq.impl.DSL
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import ru.dirtydocs.data.ProjectionContext
import ru.dirtydocs.data.Selection

class JobProjectionsTest {
    private val context = ProjectionContext(viewerId = 42)
    private val dsl = DSL.using(SQLDialect.POSTGRES)

    @Test
    fun jobMediaIsCorrelatedWithItsRequest() {
        val projection = JobProjections.REQUEST.compile(
            Selection(mapOf("media" to Selection.of("path"))),
            context,
        )

        val sql = dsl.renderInlined(projection.fields.last())

        assertTrue(sql.contains("job_media", ignoreCase = true))
        assertTrue(sql.contains("request_id", ignoreCase = true))
        assertTrue(sql.contains("processing_media_id", ignoreCase = true).not())
    }

    @Test
    fun nestedRequestsUseAnAliasedTable() {
        val projection = JobProjections.REQUEST.compile(
            Selection(mapOf("children" to Selection.of("id"))),
            context,
        )

        val sql = dsl.renderInlined(projection.fields.last())

        assertTrue(sql.contains("job_request_1", ignoreCase = true))
        assertTrue(sql.contains("parent_request_id", ignoreCase = true))
    }

    @Test
    fun eventUsesItsJobForeignKeyForTheRequestRelation() {
        val projection = JobProjections.EVENT.compile(
            Selection(mapOf("request" to Selection.of("id"))),
            context,
        )

        val sql = dsl.renderInlined(projection.fields.last())

        assertTrue(sql.contains("job_id", ignoreCase = true))
    }
}
