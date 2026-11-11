package ru.dirtydocs.api.jobs.events

import kotlinx.serialization.Serializable

@Serializable
data class JobEventData(
    val todo: Long
)
