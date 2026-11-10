package ru.dirtydocs.api.themes.collections

import org.jooq.Record
import ru.dirtydocs.api.themes.Theme
import ru.dirtydocs.api.themes.ThemeParameters
import ru.dirtydocs.api.themes.styles.Style
import ru.novari.data.ProjectionFields
import ru.novari.data.RecordView

open class ThemeCollection(
    record : Record,
    fields: ProjectionFields
) : RecordView(record, fields) {
    val id: Long
        get() = required("id")
    val name: String
        get() = required("name")
    val isPublic: Boolean
        get() = required("isPublic")
    val parameters: ThemeCollectionParameters
        get() = required("parameters")
    val themes: List<Theme>
        get() = value("themes")
    val createdAt: String
        get() = required("createdAt")
    val updatedAt: String
        get() = required("updatedAt")
}