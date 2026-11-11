package ru.dirtydocs.api.jobs.events

import org.jooq.Record
import ru.dirtydocs.api.jobs.requests.JobRequest
import ru.dirtydocs.data.ProjectionFields
import ru.dirtydocs.data.RecordView
import java.time.OffsetDateTime

open class JobEvent(
    record : Record,
    fields: ProjectionFields
) : RecordView(record, fields) {
    val id: Long
        get() = required("id")
    val request: JobRequest
        get() = value("request")
    val action: JobEventAction
        get() = JobEventAction.fromDb(required("action"))
    val data: JobEventData
        get() = required("data")
    val createdAt: OffsetDateTime
        get() = required("createdAt")
}
