package ru.dirtydocs.api.jobs.requests

import kotlinx.serialization.Serializable

@Serializable
data class JobParameters(
    val todo: Long
)
