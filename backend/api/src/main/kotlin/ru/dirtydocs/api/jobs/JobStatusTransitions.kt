package ru.dirtydocs.api.jobs

import ru.dirtydocs.api.jobs.requests.JobStatus

/** Allowed durable state transitions for a job announced by a worker. */
object JobStatusTransitions {
    val terminal = setOf(
        JobStatus.COMPLETED,
        JobStatus.COMPLETED_WITH_WARNINGS,
        JobStatus.FAILED,
        JobStatus.VALIDATION_FAILED,
        JobStatus.CANCELLED,
    )

    fun canTransition(from: JobStatus, to: JobStatus): Boolean = to in allowed.getValue(from)

    private val processingStates = setOf(
        JobStatus.PROCESSING,
        JobStatus.PARSING,
        JobStatus.RENDERING,
        JobStatus.BUILDING,
        JobStatus.VALIDATION,
    )

    private val allowed = mapOf(
        JobStatus.WAITING_FOR_MEDIA to setOf(JobStatus.QUEUED, JobStatus.CANCELLED),
        JobStatus.QUEUED to processingStates + terminal,
        JobStatus.PROCESSING to processingStates - JobStatus.PROCESSING + terminal,
        JobStatus.PARSING to setOf(JobStatus.RENDERING, JobStatus.BUILDING, JobStatus.VALIDATION) + terminal,
        JobStatus.RENDERING to setOf(JobStatus.BUILDING, JobStatus.VALIDATION) + terminal,
        JobStatus.BUILDING to setOf(JobStatus.VALIDATION) + terminal,
        JobStatus.VALIDATION to terminal,
        JobStatus.COMPLETED to emptySet(),
        JobStatus.COMPLETED_WITH_WARNINGS to emptySet(),
        JobStatus.FAILED to emptySet(),
        JobStatus.VALIDATION_FAILED to emptySet(),
        JobStatus.CANCELLED to emptySet(),
    )

}
