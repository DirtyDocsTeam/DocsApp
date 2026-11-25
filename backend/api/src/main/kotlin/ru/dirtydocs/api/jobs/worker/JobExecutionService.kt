package ru.dirtydocs.api.jobs.worker

import jakarta.enterprise.context.ApplicationScoped
import org.jooq.DSLContext
import ru.dirtydocs.api.generated.jooq.tables.JobRequest
import ru.dirtydocs.api.jobs.requests.JobStatus
import ru.dirtydocs.api.jobs.requests.JobType
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import java.util.UUID

/** Holds the workers currently available for job dispatch in this API instance. */
@ApplicationScoped
class JobExecutionService(
    private val dsl: DSLContext,
    private val workerAssignments: WorkerAssignmentClient,
) {
    private val workers = ConcurrentHashMap<String, RegisteredWorker>()
    private val occupiedWorkers = ConcurrentHashMap<String, Long>()

    /**
     * Records the endpoint advertised by a worker.
     *
     * Re-announcing the same worker replaces its endpoint and refreshes the
     * timestamp, which lets a future dispatcher treat the call as a heartbeat.
     */
    fun registerWorker(workerId: String, host: String, port: Int, supportedJobTypes: Set<JobType>) {
        workers[workerId] = RegisteredWorker(
            id = workerId,
            host = host,
            port = port,
            supportedJobTypes = supportedJobTypes,
            announcedAt = Instant.now(),
        )
    }

    fun worker(workerId: String): RegisteredWorker? = workers[workerId]

    /** Returns a snapshot for the dispatcher to select an available worker. */
    fun registeredWorkers(): List<RegisteredWorker> = workers.values.toList()

    /** Returns workers that announced support for the requested job type. */
    fun registeredWorkersFor(jobType: JobType): List<RegisteredWorker> =
        workers.values.filter { jobType in it.supportedJobTypes }

    fun getTaskQuery(filter: Set<JobType>) =
        dsl.selectFrom(JobRequest.JOB_REQUEST)
            .where(JobRequest.JOB_REQUEST.STATUS.eq(JobStatus.QUEUED.dbValue))
            .and(JobRequest.JOB_REQUEST.DELETED_AT.isNull)
            .and(JobRequest.JOB_REQUEST.TYPE.`in`(filter.map { it.dbValue }))
            .orderBy(JobRequest.JOB_REQUEST.CREATED_AT.asc())

    fun dispatchQuery(): Boolean {
        var dispatched = false
        workers.entries
            .filterNot { occupiedWorkers.containsKey(it.key) }
            .forEach { (workerId, worker) ->
                val job = getTaskQuery(worker.supportedJobTypes).fetchOne() ?: return@forEach
                val jobId = requireNotNull(job[JobRequest.JOB_REQUEST.ID])
                if (occupiedWorkers.putIfAbsent(workerId, jobId) != null) return@forEach

                val deliveryKey = UUID.randomUUID().toString()
                if (!claimJobDelivery(jobId, deliveryKey)) {
                    freeWorkerJob(workerId)
                    return@forEach
                }
                workerAssignments.assign(worker, jobId, deliveryKey)
                    .subscribe()
                    .with({ accepted ->
                        if (!accepted) releaseAssignment(workerId, jobId, deliveryKey)
                    }, {
                        releaseAssignment(workerId, jobId, deliveryKey)
                    })
                dispatched = true
            }
        return dispatched
    }

    fun freeWorker(workerId: String) {
        workers.remove(workerId)
        freeWorkerJob(workerId)
    }

    /** Releases the worker assigned to a job after its execution is over or cancelled. */
    fun freeWorkerJob(jobId: Long) {
        occupiedWorkers.entries.removeIf { it.value == jobId }
    }

    private fun freeWorkerJob(workerId: String) {
        occupiedWorkers.remove(workerId)
    }

    private fun claimJobDelivery(jobId: Long, deliveryKey: String): Boolean =
        dsl.update(JobRequest.JOB_REQUEST)
            .set(JobRequest.JOB_REQUEST.DELIVERY_KEY, deliveryKey)
            .set(JobRequest.JOB_REQUEST.DELIVERY_ATTEMPTS, JobRequest.JOB_REQUEST.DELIVERY_ATTEMPTS.plus(1))
            .where(JobRequest.JOB_REQUEST.ID.eq(jobId))
            .and(JobRequest.JOB_REQUEST.STATUS.eq(JobStatus.QUEUED.dbValue))
            .and(JobRequest.JOB_REQUEST.DELIVERY_KEY.isNull)
            .and(JobRequest.JOB_REQUEST.DELETED_AT.isNull)
            .execute() == 1

    private fun releaseAssignment(workerId: String, jobId: Long, deliveryKey: String) {
        freeWorkerJob(workerId)
        dsl.update(JobRequest.JOB_REQUEST)
            .setNull(JobRequest.JOB_REQUEST.DELIVERY_KEY)
            .where(JobRequest.JOB_REQUEST.ID.eq(jobId))
            .and(JobRequest.JOB_REQUEST.DELIVERY_KEY.eq(deliveryKey))
            .and(JobRequest.JOB_REQUEST.STATUS.eq(JobStatus.QUEUED.dbValue))
            .execute()
    }
}

data class RegisteredWorker(
    val id: String,
    val host: String,
    val port: Int,
    val supportedJobTypes: Set<JobType>,
    val announcedAt: Instant,
)
