package ru.dirtydocs.api.themes.styles

enum class StyleType(val dbValue: String) {
    TRANSFORM("transform"),
    RENDER("render"),
    VALIDATION("validation");

    companion object {
        fun fromDb(value: String): StyleType =
            StyleType.entries.firstOrNull { it.dbValue == value }
                ?: error("Unknown style type '$value'")
    }
}