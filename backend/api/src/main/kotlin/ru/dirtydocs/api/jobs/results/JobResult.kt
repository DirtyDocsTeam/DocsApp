package ru.dirtydocs.api.jobs.results

import org.jooq.Record
import ru.dirtydocs.api.jobs.requests.JobRequest
import ru.dirtydocs.api.media.Media
import ru.dirtydocs.data.ProjectionFields
import ru.dirtydocs.data.RecordView
import java.time.OffsetDateTime

open class JobResult(
    record : Record,
    fields: ProjectionFields
) : RecordView(record, fields) {
    val id: String
        get() = required("id")
    val request: JobRequest
        get() = value("request")
    val media: Media
        get() = value("media")
    val completedAt: OffsetDateTime
        get() = required("completedAt")
}
