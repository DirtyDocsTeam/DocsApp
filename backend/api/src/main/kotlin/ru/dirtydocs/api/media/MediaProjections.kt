package ru.dirtydocs.api.media

import org.jooq.Condition
import org.jooq.Table
import org.jooq.impl.DSL
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_MEDIA as JOB_MEDIA_TABLE
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_REQUEST
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_RESULT as JOB_RESULT_TABLE
import ru.dirtydocs.api.generated.jooq.tables.references.MEDIA
import ru.dirtydocs.data.Projection
import ru.dirtydocs.data.ProjectionContext
import ru.dirtydocs.data.columnNodes

object MediaProjections {
    private val baseMediaNodes = columnNodes(
        mapOf(
            "id" to MEDIA.ID,
            "isPrivate" to MEDIA.IS_NON_CACHEABLE,
            "mimeType" to MEDIA.MIME_TYPE
        )
    )
    val jobMediaTable: Table<*> = JOB_MEDIA_TABLE.join(MEDIA)
        .on(JOB_MEDIA_TABLE.MEDIA_ID.eq(MEDIA.ID))
    private val resultMediaTable: Table<*> = JOB_RESULT_TABLE.join(MEDIA)
        .on(JOB_RESULT_TABLE.RESULT_MEDIA_ID.eq(MEDIA.ID))

    val JOB_MEDIA: Projection<Media> = Projection(
        table = jobMediaTable,
        id = MEDIA.ID,
        nodes = baseMediaNodes + columnNodes(mapOf("path" to JOB_MEDIA_TABLE.PUBLIC_PATH)),
        required = setOf("id"),
        factory = ::Media,
        access = ::jobMediaAccess,
    )
    val RESULT_MEDIA: Projection<Media> = Projection(
        table = resultMediaTable,
        id = MEDIA.ID,
        nodes = baseMediaNodes + columnNodes(mapOf("path" to JOB_RESULT_TABLE.EXTERNAL_ID)),
        required = setOf("id"),
        factory = ::Media,
        access = ::resultMediaAccess,
    )

    private fun jobMediaAccess(context: ProjectionContext): Condition =
        context.viewerId?.let { viewerId ->
            JOB_MEDIA_TABLE.REQUEST_ID.`in`(
                DSL.select(JOB_REQUEST.ID)
                    .from(JOB_REQUEST)
                    .where(JOB_REQUEST.USER_ID.eq(viewerId))
            )
        } ?: DSL.falseCondition()

    private fun resultMediaAccess(context: ProjectionContext): Condition =
        context.viewerId?.let { viewerId ->
            JOB_RESULT_TABLE.REQUEST_ID.`in`(
                DSL.select(JOB_REQUEST.ID)
                    .from(JOB_REQUEST)
                    .where(JOB_REQUEST.USER_ID.eq(viewerId))
            )
        } ?: DSL.falseCondition()
}
