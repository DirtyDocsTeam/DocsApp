package ru.dirtydocs.api.auth

/** Opaque API token parsed from the wire format. Its string form deliberately redacts the secret. */
class ApiTokenCredentials(
    val id: Long,
    val secret: String,
) {
    companion object {
        private val format = Regex("ddat_([1-9][0-9]*)_(.+)")

        fun parse(value: String): ApiTokenCredentials? {
            val match = format.matchEntire(value) ?: return null
            val id = match.groupValues[1].toLongOrNull() ?: return null
            return ApiTokenCredentials(id, match.groupValues[2])
        }
    }

    override fun toString(): String = "ApiTokenCredentials(id=$id, secret=[redacted])"
}
