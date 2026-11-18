package ru.dirtydocs.api.subscriptions

import io.smallrye.mutiny.Multi
import io.smallrye.mutiny.operators.multi.processors.BroadcastProcessor
import jakarta.enterprise.context.ApplicationScoped
import ru.dirtydocs.api.jobs.requests.JobStatus
import java.time.OffsetDateTime

data class JobStatusChange(
    val jobId: String,
    val status: JobStatus,
    val updatedAt: OffsetDateTime,
)

data class ThemeChange(
    val themeId: Long,
    val action: ThemeChangeAction,
    val updatedAt: OffsetDateTime,
)

enum class ThemeChangeAction { CREATED, UPDATED, DELETED }

/**
 * Delivers local GraphQL subscription notifications.
 *
 * A later outbox consumer must call the same publish methods after a committed
 * cross-instance event, because a processor is intentionally process-local.
 */
@ApplicationScoped
class DomainEventPublisher {
    private val jobChanges = BroadcastProcessor.create<OwnedJobStatusChange>()
    private val themeChanges = BroadcastProcessor.create<OwnedThemeChange>()

    fun publishJob(userId: Long, change: JobStatusChange) {
        jobChanges.onNext(OwnedJobStatusChange(userId, change))
    }

    fun publishTheme(userId: Long, isPublic: Boolean, change: ThemeChange) {
        themeChanges.onNext(OwnedThemeChange(userId, isPublic, change))
    }

    fun jobChangesFor(userId: Long, jobId: String): Multi<JobStatusChange> = jobChanges
        .select().where { event -> event.userId == userId && event.change.jobId == jobId }
        .map { it.change }

    fun themeChangesFor(userId: Long): Multi<ThemeChange> = themeChanges
        .select().where { event -> event.userId == userId || event.isPublic }
        .map { it.change }

    private data class OwnedJobStatusChange(val userId: Long, val change: JobStatusChange)
    private data class OwnedThemeChange(val userId: Long, val isPublic: Boolean, val change: ThemeChange)
}
