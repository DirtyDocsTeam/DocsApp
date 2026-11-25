package ru.dirtydocs.api.jobs.worker

import jakarta.enterprise.context.ApplicationScoped

/** Maps an authenticated worker announcement to the local worker registry. */
@ApplicationScoped
class WorkerAnnouncementController(
    private val jobExecution: JobExecutionService,
) {
    fun announce(workerId: String, host: String, port: Int) =
        jobExecution.registerWorker(workerId, host, port)
}
