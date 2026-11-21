package ru.dirtydocs.api.jobs.events

enum class JobEventAction(val dbValue: String) {
    CREATE_JOB("create_job"),
    JOB_COMPLETED("job_completed"),
    JOB_FAILED("job_failed"),
    ISSUE_DOWNLOAD_URL("issue_download_url");

    companion object {
        fun fromDb(value: String): JobEventAction =
            entries.firstOrNull { it.dbValue == value }
                ?: error("Unknown job event action '$value'")
    }
}
