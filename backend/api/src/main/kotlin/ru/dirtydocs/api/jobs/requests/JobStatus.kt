package ru.dirtydocs.api.jobs.requests

enum class JobStatus(val dbValue: String) {
    QUEUED("queued"),
    PROCESSING("processing"),
    PARSING("parsing"),
    RENDERING("rendering"),
    BUILDING("building"),
    VALIDATION("validation"),
    COMPLETED("completed"),
    COMPLETED_WITH_WARNINGS("completed_with_warnings"),
    FAILED("failed"),
    VALIDATION_FAILED("validation_failed");

    companion object {
        fun fromDb(value: String): JobStatus =
            entries.firstOrNull { it.dbValue == value }
                ?: error("Unknown job status '$value'")
    }
}
