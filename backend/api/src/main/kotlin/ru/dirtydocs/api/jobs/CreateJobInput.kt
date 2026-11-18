package ru.dirtydocs.api.jobs

import ru.dirtydocs.api.jobs.requests.JobParameters
import ru.dirtydocs.api.jobs.requests.JobType

data class CreateJobInput(
    val primaryMediaHash: String,
    val attachmentMediaHashes: List<String> = emptyList(),
    val inputType: String,
    val outputType: String,
    val type: JobType,
    val themeId: Long,
    val parameters: JobParameters,
    val idempotencyKey: String,
)
