package ru.dirtydocs.api.themes.styles

import org.jooq.Record
import ru.dirtydocs.data.ProjectionFields
import ru.dirtydocs.data.RecordView

open class Style(
    record : Record,
    fields: ProjectionFields
) : RecordView(record, fields) {
    val id: Long
        get() = required("id")
    val type: StyleType
        get() = StyleType.fromDb(required("type"))
    val exampleText: String
        get() = required("exampleText")
    val styleDescription: StyleDescription
        get() = value("styleDescription")
}