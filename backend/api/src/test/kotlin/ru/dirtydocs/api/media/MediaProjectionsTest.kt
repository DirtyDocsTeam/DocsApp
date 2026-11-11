package ru.dirtydocs.api.media

import org.jooq.SQLDialect
import org.jooq.impl.DSL
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import ru.dirtydocs.data.ProjectionContext
import ru.dirtydocs.data.Selection

class MediaProjectionsTest {
    @Test
    fun jobMediaUsesItsPublicPathAndTheOwningJobForAccess() {
        val projection = MediaProjections.JOB_MEDIA.compile(
            Selection.of("id", "path"),
            ProjectionContext(viewerId = 42),
        )
        val dsl = DSL.using(SQLDialect.POSTGRES)

        assertTrue(dsl.renderInlined(projection.table).contains("job_media", ignoreCase = true))
        assertTrue(dsl.renderInlined(projection.fields.last()).contains("public_path", ignoreCase = true))
        assertTrue(dsl.renderInlined(projection.condition).contains("job_media", ignoreCase = true))
        assertTrue(dsl.renderInlined(projection.condition).contains("job_request", ignoreCase = true))
    }

    @Test
    fun resultMediaUsesItsExternalIdAndTheOwningJobForAccess() {
        val projection = MediaProjections.RESULT_MEDIA.compile(
            Selection.of("id", "path"),
            ProjectionContext(viewerId = 42),
        )
        val dsl = DSL.using(SQLDialect.POSTGRES)

        assertTrue(dsl.renderInlined(projection.table).contains("job_result", ignoreCase = true))
        assertTrue(dsl.renderInlined(projection.fields.last()).contains("external_id", ignoreCase = true))
        assertTrue(dsl.renderInlined(projection.condition).contains("job_result", ignoreCase = true))
        assertTrue(dsl.renderInlined(projection.condition).contains("job_request", ignoreCase = true))
    }

    @Test
    fun anonymousViewerCannotAccessMedia() {
        val dsl = DSL.using(SQLDialect.POSTGRES)

        assertTrue(
            dsl.renderInlined(
                MediaProjections.JOB_MEDIA.compile(Selection.of("id"), ProjectionContext(viewerId = null)).condition,
            ).contains("false", ignoreCase = true)
        )
        assertTrue(
            dsl.renderInlined(
                MediaProjections.RESULT_MEDIA.compile(Selection.of("id"), ProjectionContext(viewerId = null)).condition,
            ).contains("false", ignoreCase = true)
        )
    }
}
