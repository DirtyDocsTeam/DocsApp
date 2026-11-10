package ru.dirtydocs.api.themes.collections


enum class ThemeCollectionRole(val dbValue: String) {
    VIEWER("viewer"),
    EDITOR("editor"),
    ADMIN("admin"),
    OWNER("owner");

    companion object {
        fun fromDb(value: String): ThemeCollectionRole =
            ThemeCollectionRole.entries.firstOrNull { it.dbValue == value }
                ?: error("Unknown theme collection role '$value'")
    }
}