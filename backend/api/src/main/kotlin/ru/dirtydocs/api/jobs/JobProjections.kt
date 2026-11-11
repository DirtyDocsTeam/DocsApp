package ru.dirtydocs.api.jobs

import kotlinx.serialization.json.Json
import org.jooq.Condition
import org.jooq.Field
import org.jooq.Table
import org.jooq.impl.DSL
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_EVENTS
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_MEDIA
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_REQUEST
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_RESULT
import ru.dirtydocs.api.generated.jooq.tables.references.MEDIA
import ru.dirtydocs.api.jobs.events.JobEvent
import ru.dirtydocs.api.jobs.events.JobEventData
import ru.dirtydocs.api.jobs.requests.JobParameters
import ru.dirtydocs.api.jobs.requests.JobRequest
import ru.dirtydocs.api.jobs.results.JobResult
import ru.dirtydocs.api.media.MediaProjections
import ru.dirtydocs.api.themes.ThemeProjections
import ru.dirtydocs.data.ManyRelation
import ru.dirtydocs.data.OneRelation
import ru.dirtydocs.data.Projection
import ru.dirtydocs.data.ProjectionContext
import ru.dirtydocs.data.ProjectionNode
import ru.dirtydocs.data.columnNodes
import ru.dirtydocs.data.jsonb

object JobProjections {
    private const val maxNestedRequestDepth = 5

    private val json = Json {
        ignoreUnknownKeys = true
        decodeEnumsCaseInsensitive = true
    }
    private val requestTables = (0..maxNestedRequestDepth).map { depth ->
        if (depth == 0) JOB_REQUEST else JOB_REQUEST.`as`("job_request_$depth")
    }
    private val requestProjections: List<Projection<JobRequest>> by lazy {
        requestTables.mapIndexed(::requestProjection)
    }

    val REQUEST: Projection<JobRequest>
        get() = requestProjections.first()

    private fun requestProjection(depth: Int, table: Table<*>): Projection<JobRequest> = Projection(
        table = table,
        id = table.fieldOf(JOB_REQUEST.ID),
        nodes = columnNodes(
            mapOf(
                "id" to table.fieldOf(JOB_REQUEST.EXTERNAL_ID),
                "inputType" to table.fieldOf(JOB_REQUEST.INPUT_TYPE),
                "outputType" to table.fieldOf(JOB_REQUEST.OUTPUT_TYPE),
                "type" to table.fieldOf(JOB_REQUEST.TYPE),
                "status" to table.fieldOf(JOB_REQUEST.STATUS),
                "parameters" to jsonb(table.fieldOf(JOB_REQUEST.PARAMETERS), JobParameters.serializer(), json),
                "createdAt" to table.fieldOf(JOB_REQUEST.CREATED_AT),
                "updatedAt" to table.fieldOf(JOB_REQUEST.UPDATED_AT),
            )
        ) + requestRelations(depth, table),
        required = setOf("id"),
        factory = ::JobRequest,
        access = { context -> requestAccess(table, context) },
    )

    private fun requestRelations(depth: Int, table: Table<*>): Map<String, ProjectionNode> {
        val relations = linkedMapOf<String, ProjectionNode>(
            "processingMedia" to OneRelation(
                childProvider = { MediaProjections.JOB_MEDIA },
                parentForeignKey = table.fieldOf(JOB_REQUEST.PROCESSING_MEDIA_ID),
            ),
            "media" to ManyRelation(
                childProvider = { MediaProjections.JOB_MEDIA },
                relationCondition = { MediaProjections.jobMediaTable
                    .field(JOB_MEDIA.REQUEST_ID)!!
                    .eq(table.fieldOf(JOB_REQUEST.ID)) },
                orderBy = {
                    listOf(MediaProjections.jobMediaTable
                        .field(MEDIA.ID)!!.desc())
                },
            ),
            "theme" to OneRelation(
                childProvider = { ThemeProjections.THEME },
                parentForeignKey = table.fieldOf(JOB_REQUEST.THEME_ID),
            ),
        )
        if (depth < maxNestedRequestDepth) {
            val nestedTable = requestTables[depth + 1]
            relations["parent"] = OneRelation(
                childProvider = { requestProjections[depth + 1] },
                parentForeignKey = table.fieldOf(JOB_REQUEST.PARENT_REQUEST_ID),
            )
            relations["children"] = ManyRelation(
                childProvider = { requestProjections[depth + 1] },
                relationCondition = {
                    nestedTable.fieldOf(JOB_REQUEST.PARENT_REQUEST_ID)
                        .eq(table.fieldOf(JOB_REQUEST.ID))
                },
                orderBy = {
                    listOf(
                        nestedTable.fieldOf(JOB_REQUEST.CREATED_AT).desc(),
                        nestedTable.fieldOf(JOB_REQUEST.ID).desc(),
                    )
                },
            )
        }
        return relations
    }
    val RESULT: Projection<JobResult> = Projection(
        table = JOB_RESULT,
        id = JOB_RESULT.ID,
        nodes = columnNodes(
            mapOf(
                "id" to JOB_RESULT.EXTERNAL_ID,
                "completedAt" to JOB_RESULT.COMPLETED_AT
            )
        ) + mapOf(
            "request" to OneRelation(
                childProvider = { REQUEST },
                parentForeignKey = JOB_RESULT.REQUEST_ID,
            ),
            "media" to OneRelation(
                childProvider = { MediaProjections.RESULT_MEDIA },
                parentForeignKey = JOB_RESULT.RESULT_MEDIA_ID,
            )
        ),
        required = setOf("id"),
        factory = ::JobResult,
        access = { context ->
            context.viewerId?.let { viewerId ->
                JOB_RESULT.REQUEST_ID.`in`(
                    DSL.select(JOB_REQUEST.ID)
                        .from(JOB_REQUEST)
                        .where(JOB_REQUEST.USER_ID.eq(viewerId))
                )
            } ?: DSL.falseCondition()
        },
    )

    val EVENT: Projection<JobEvent> = Projection(
        table = JOB_EVENTS,
        id = JOB_EVENTS.ID,
        nodes = columnNodes(
            mapOf(
                "id" to JOB_EVENTS.ID,
                "action" to JOB_EVENTS.ACTION,
                "data" to jsonb(JOB_EVENTS.DATA, JobEventData.serializer(), json),
                "createdAt" to JOB_EVENTS.CREATED_AT
            )
        ) + mapOf(
            "request" to OneRelation(
                childProvider = { REQUEST },
                parentForeignKey = JOB_EVENTS.JOB_ID,
            )
        ),
        required = setOf("id"),
        factory = ::JobEvent,
        access = { context ->
            context.viewerId?.let { viewerId ->
                JOB_EVENTS.JOB_ID.`in`(
                    DSL.select(JOB_REQUEST.ID)
                        .from(JOB_REQUEST)
                        .where(JOB_REQUEST.USER_ID.eq(viewerId))
                )
            } ?: DSL.falseCondition()
        }
    )

    private fun requestAccess(table: Table<*>, context: ProjectionContext): Condition =
        context.viewerId?.let { viewerId ->
            table.fieldOf(JOB_REQUEST.USER_ID).eq(viewerId)
        } ?: DSL.falseCondition()

    private fun <T> Table<*>.fieldOf(field: Field<T>): Field<T> =
        requireNotNull(field(field)) { "Table does not contain ${field.qualifiedName}" }
}
