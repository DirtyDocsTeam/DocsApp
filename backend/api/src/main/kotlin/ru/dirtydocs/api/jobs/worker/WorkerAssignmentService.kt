package ru.dirtydocs.api.jobs.worker

import io.smallrye.mutiny.Uni
import jakarta.enterprise.context.ApplicationScoped
import org.jooq.DSLContext
import ru.dirtydocs.api.generated.jooq.tables.JobRequest.Companion.JOB_REQUEST
import ru.dirtydocs.api.jobs.requests.JobStatus
import java.util.UUID

/**
 * Reserves a queued job for one worker delivery and sends that delivery once.
 *
 * A delivery retry reuses its key so workers can safely de-duplicate it. A
 * future explicit reassignment must issue a new key after the prior worker is
 * known to be unavailable.
 */
@ApplicationScoped
class WorkerAssignmentService(
    private val dsl: DSLContext,
    private val workers: WorkerAssignmentClient,
) {
    fun assign(jobId: Long): Uni<Boolean> {
        val job = dsl.select(JOB_REQUEST.DELIVERY_KEY)
            .from(JOB_REQUEST)
            .where(JOB_REQUEST.ID.eq(jobId))
            .and(JOB_REQUEST.STATUS.eq(JobStatus.QUEUED.dbValue))
            .and(JOB_REQUEST.DELETED_AT.isNull)
            .fetchOne()
            ?: return Uni.createFrom().item(false)
        val currentKey = job[JOB_REQUEST.DELIVERY_KEY]
        val deliveryKey = currentKey ?: UUID.randomUUID().toString()
        val updated = dsl.update(JOB_REQUEST)
            .set(JOB_REQUEST.DELIVERY_KEY, deliveryKey)
            .set(JOB_REQUEST.DELIVERY_ATTEMPTS, JOB_REQUEST.DELIVERY_ATTEMPTS.plus(1))
            .where(JOB_REQUEST.ID.eq(jobId))
            .and(JOB_REQUEST.STATUS.eq(JobStatus.QUEUED.dbValue))
            .and(
                if (currentKey == null) {
                    JOB_REQUEST.DELIVERY_KEY.isNull
                } else {
                    JOB_REQUEST.DELIVERY_KEY.eq(currentKey)
                },
            )
            .and(JOB_REQUEST.DELETED_AT.isNull)
            .execute()
        if (updated != 1) return Uni.createFrom().item(false)
        return workers.assign(jobId, deliveryKey)
    }
}
