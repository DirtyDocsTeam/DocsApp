package ru.dirtydocs.api.users

enum class UserRole(val dbValue: String) {
    ADMIN("admin"),
    USER("user");

    companion object {
        fun fromDb(value: String): UserRole =
            UserRole.entries.firstOrNull { it.dbValue == value }
                ?: error("Unknown role '$value'")
    }
}