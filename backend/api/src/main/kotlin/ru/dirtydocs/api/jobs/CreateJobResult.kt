package ru.dirtydocs.api.jobs

import ru.dirtydocs.api.jobs.requests.JobRequest

data class CreateJobResult(
    val job: JobRequest,
    val missingMediaHashes: List<String>,
)
