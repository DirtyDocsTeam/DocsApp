package ru.dirtydocs.api.themes

import org.jooq.Record
import ru.dirtydocs.api.themes.styles.Style
import ru.dirtydocs.data.ProjectionFields
import ru.dirtydocs.data.RecordView

open class Theme(
    record : Record,
    fields: ProjectionFields
) : RecordView(record, fields) {
    val id: Long
        get() = required("id")
    val name: String
        get() = required("name")
    val isPublic: Boolean
        get() = required("isPublic")
    val parameters: ThemeParameters
        get() = required("parameters")
    val styles: List<Style>
        get() = value("styles")
    val createdAt: String
        get() = required("createdAt")
    val updatedAt: String
        get() = required("updatedAt")
}