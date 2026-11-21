package ru.dirtydocs.api.users

import org.jooq.Record
import ru.dirtydocs.api.users.tokens.Token
import ru.dirtydocs.data.ProjectionFields
import ru.dirtydocs.data.RecordView
import java.time.OffsetDateTime

open class User(
    record : Record,
    fields: ProjectionFields
) : RecordView(record, fields) {
    val id: Long
        get() = required("id")
    val email: String
        get() = required("email")
    val roles: Set<UserRole>
        get() {
            val roleData: List<String?> = required("roles")
            return roleData.mapNotNull {
                it?.let {
                    UserRole.valueOf(it)
                }
            }.toSet()
        }
    val createdAt: OffsetDateTime
        get() = required("createdAt")
    val updatedAt: OffsetDateTime
        get() = required("updatedAt")
    val tokens: Long
        get() = required("tokens")
    val lastTokenChangeAt: OffsetDateTime
        get() = required("lastTokenChangeAt")
    val apiTokens: List<Token>
        get() = value("apiTokens")
}
