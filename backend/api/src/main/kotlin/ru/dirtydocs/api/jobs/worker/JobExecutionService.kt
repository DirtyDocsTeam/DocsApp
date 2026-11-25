package ru.dirtydocs.api.jobs.worker

import jakarta.enterprise.context.ApplicationScoped
import org.jooq.DSLContext
import ru.dirtydocs.api.generated.jooq.tables.JobRequest
import ru.dirtydocs.api.jobs.requests.JobStatus
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap

/** Holds the workers currently available for job dispatch in this API instance. */
@ApplicationScoped
class JobExecutionService(
    private val dsl: DSLContext,
) {
    private val workers = ConcurrentHashMap<String, RegisteredWorker>()

    /**
     * Records the endpoint advertised by a worker.
     *
     * Re-announcing the same worker replaces its endpoint and refreshes the
     * timestamp, which lets a future dispatcher treat the call as a heartbeat.
     */
    fun registerWorker(workerId: String, host: String, port: Int) {
        workers[workerId] = RegisteredWorker(
            id = workerId,
            host = host,
            port = port,
            announcedAt = Instant.now(),
        )
    }

    fun worker(workerId: String): RegisteredWorker? = workers[workerId]

    /** Returns a snapshot for the dispatcher to select an available worker. */
    fun registeredWorkers(): List<RegisteredWorker> = workers.values.toList()

    fun getTaskQuery() =
        dsl.selectFrom(JobRequest.JOB_REQUEST)
            .where(JobRequest.JOB_REQUEST.STATUS.eq(JobStatus.QUEUED.dbValue))
            .and(JobRequest.JOB_REQUEST.DELETED_AT.isNull)
            .orderBy(JobRequest.JOB_REQUEST.CREATED_AT.asc())
}

data class RegisteredWorker(
    val id: String,
    val host: String,
    val port: Int,
    val announcedAt: Instant,
)
