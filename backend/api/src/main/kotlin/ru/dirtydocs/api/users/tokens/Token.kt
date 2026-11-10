package ru.dirtydocs.api.users.tokens

import org.jooq.Record
import ru.dirtydocs.api.users.tokens.access.TokenAccessRights
import ru.novari.data.ProjectionFields
import ru.novari.data.RecordView
import java.time.OffsetDateTime

open class Token(
    record : Record,
    fields: ProjectionFields
) : RecordView(record, fields) {
    val id: Long
        get() = required("id")
    val createdAt: OffsetDateTime
        get() = required("createdAt")
    val expiresAt: OffsetDateTime
        get() = required("expiresAt")
    val access : TokenAccessRights
        get() = value("access")
}