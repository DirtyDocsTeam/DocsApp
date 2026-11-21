package ru.dirtydocs.api.media

import org.jooq.Record
import ru.dirtydocs.data.ProjectionFields
import ru.dirtydocs.data.RecordView

open class Media(
    record : Record,
    fields: ProjectionFields
) : RecordView(record, fields) {
    val isPrivate: Boolean
        get() = required("isPrivate")
    val mimeType: String
        get() = required("mimeType")
    val path: String
        get() = required("path")
}
