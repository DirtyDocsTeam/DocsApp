package ru.dirtydocs.api.jobs

import jakarta.enterprise.context.ApplicationScoped
import org.jooq.DSLContext
import org.jooq.impl.DSL
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_MEDIA
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_REQUEST
import ru.dirtydocs.api.generated.jooq.tables.references.MEDIA
import ru.dirtydocs.api.jobs.requests.JobStatus
import ru.dirtydocs.api.subscriptions.DomainEventPublisher
import ru.dirtydocs.api.subscriptions.JobStatusChange
import java.time.OffsetDateTime

/**
 * Applies a worker status announcement exactly once per status value.
 *
 * The future mTLS gRPC adapter must authenticate the worker and invoke this
 * service only after validating its delivery key.
 */
@ApplicationScoped
class JobStatusService(
    private val dsl: DSLContext,
    private val events: DomainEventPublisher,
) {
    fun announce(jobId: Long, status: JobStatus): Boolean {
        val current = dsl.select(JOB_REQUEST.STATUS)
            .from(JOB_REQUEST)
            .where(JOB_REQUEST.ID.eq(jobId))
            .and(deletedAt.isNull)
            .fetchOne(JOB_REQUEST.STATUS)
            ?.let(JobStatus::fromDb)
            ?: return false
        if (status !in allowedTransitions.getValue(current)) return false
        val changed = dsl.update(JOB_REQUEST)
            .set(JOB_REQUEST.STATUS, status.dbValue)
            .where(JOB_REQUEST.ID.eq(jobId))
            .and(JOB_REQUEST.STATUS.eq(current.dbValue))
            .and(deletedAt.isNull)
            .execute()
        if (changed != 1) return false

        val job = dsl.select(JOB_REQUEST.USER_ID, JOB_REQUEST.EXTERNAL_ID, JOB_REQUEST.UPDATED_AT)
            .from(JOB_REQUEST)
            .where(JOB_REQUEST.ID.eq(jobId))
            .fetchOne()
            ?: return false
        if (status in terminalStatuses) expireUnusedNonCacheableMedia(jobId)
        events.publishJob(
            requireNotNull(job[JOB_REQUEST.USER_ID]),
            JobStatusChange(
                requireNotNull(job[JOB_REQUEST.EXTERNAL_ID]),
                status,
                requireNotNull(job[JOB_REQUEST.UPDATED_AT]),
            ),
        )
        return true
    }

    private fun expireUnusedNonCacheableMedia(jobId: Long) {
        val activeMedia = DSL.select(JOB_MEDIA.MEDIA_ID)
            .from(JOB_MEDIA)
            .join(JOB_REQUEST).on(JOB_MEDIA.REQUEST_ID.eq(JOB_REQUEST.ID))
            .where(JOB_REQUEST.STATUS.notIn(terminalStatusValues))
        dsl.update(MEDIA)
            .set(MEDIA.DELETE_AT, OffsetDateTime.now())
            .where(MEDIA.ID.`in`(DSL.select(JOB_MEDIA.MEDIA_ID).from(JOB_MEDIA).where(JOB_MEDIA.REQUEST_ID.eq(jobId))))
            .and(MEDIA.IS_NON_CACHEABLE.eq(true))
            .and(MEDIA.ID.notIn(activeMedia))
            .execute()
    }

    private companion object {
        val terminalStatuses = setOf(
            JobStatus.COMPLETED,
            JobStatus.COMPLETED_WITH_WARNINGS,
            JobStatus.FAILED,
            JobStatus.VALIDATION_FAILED,
            JobStatus.CANCELLED,
        )
        val terminalStatusValues = terminalStatuses.map(JobStatus::dbValue)
        val allowedTransitions = mapOf(
            JobStatus.WAITING_FOR_MEDIA to setOf(JobStatus.QUEUED, JobStatus.CANCELLED),
            JobStatus.QUEUED to setOf(JobStatus.PROCESSING, JobStatus.PARSING, JobStatus.RENDERING, JobStatus.BUILDING, JobStatus.VALIDATION) + terminalStatuses,
            JobStatus.PROCESSING to setOf(JobStatus.PARSING, JobStatus.RENDERING, JobStatus.BUILDING, JobStatus.VALIDATION) + terminalStatuses,
            JobStatus.PARSING to setOf(JobStatus.RENDERING, JobStatus.BUILDING, JobStatus.VALIDATION) + terminalStatuses,
            JobStatus.RENDERING to setOf(JobStatus.BUILDING, JobStatus.VALIDATION) + terminalStatuses,
            JobStatus.BUILDING to setOf(JobStatus.VALIDATION) + terminalStatuses,
            JobStatus.VALIDATION to terminalStatuses,
            JobStatus.COMPLETED to emptySet(),
            JobStatus.COMPLETED_WITH_WARNINGS to emptySet(),
            JobStatus.FAILED to emptySet(),
            JobStatus.VALIDATION_FAILED to emptySet(),
            JobStatus.CANCELLED to emptySet(),
        )
        val deletedAt = DSL.field(DSL.name("job_request", "deleted_at"), OffsetDateTime::class.java)
    }
}
