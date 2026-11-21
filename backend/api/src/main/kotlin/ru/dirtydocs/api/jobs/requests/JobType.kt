package ru.dirtydocs.api.jobs.requests

enum class JobType(val dbValue: String) {
    TEMPLATING("templating"),
    CONVERSION("conversion"),
    VALIDATION("validation");

    companion object {
        fun fromDb(value: String): JobType =
            entries.firstOrNull { it.dbValue == value }
                ?: error("Unknown job type '$value'")
    }
}
