package ru.dirtydocs.api.jobs.requests

import org.jooq.Record
import ru.dirtydocs.api.jobs.results.JobResult
import ru.dirtydocs.api.media.Media
import ru.dirtydocs.api.themes.Theme
import ru.dirtydocs.data.ProjectionFields
import ru.dirtydocs.data.RecordView
import java.time.OffsetDateTime

open class JobRequest(
    record : Record,
    fields: ProjectionFields
) : RecordView(record, fields) {
    val id: String
        get() = required("id")
    val parent: JobRequest?
        get() = value("parent")
    val children: List<JobRequest>
        get() = value("children")
    val processingMedia: Media
        get() = value("processingMedia")
    val media: List<Media>
        get() = value("media")
    val inputType: String
        get() = required("inputType")
    val outputType: String
        get() = required("outputType")
    val type: JobType
        get() = JobType.fromDb(required("type"))
    val status: JobStatus
        get() = JobStatus.fromDb(required("status"))
    val theme: Theme
        get() = value("theme")
    val results: List<JobResult>
        get() = value("results")
    val parameters: JobParameters
        get() = value("parameters")
    val createdAt: OffsetDateTime
        get() = required("createdAt")
    val updatedAt: OffsetDateTime
        get() = required("updatedAt")
}
