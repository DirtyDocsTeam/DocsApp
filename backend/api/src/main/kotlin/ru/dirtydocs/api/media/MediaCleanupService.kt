package ru.dirtydocs.api.media

import io.quarkus.scheduler.Scheduled
import jakarta.enterprise.context.ApplicationScoped
import jakarta.enterprise.inject.Instance
import org.jooq.DSLContext
import org.jooq.impl.DSL
import ru.dirtydocs.api.generated.jooq.tables.references.MEDIA
import java.time.OffsetDateTime

/** Retries overdue cache eviction without deleting metadata that preserves job history. */
@ApplicationScoped
class MediaCleanupService(
    private val dsl: DSLContext,
    private val gateway: Instance<MediaEvictionGateway>,
) {
    @Scheduled(every = "1m", concurrentExecution = Scheduled.ConcurrentExecution.SKIP)
    fun evictExpiredMedia() {
        if (!gateway.isResolvable) return
        val candidates = dsl.transactionResult { configuration ->
            val tx = DSL.using(configuration)
            val candidates = tx
                .select(MEDIA.ID, MEDIA.STORAGE_PATH)
                .from(MEDIA)
                .where(MEDIA.DELETE_AT.le(OffsetDateTime.now()))
                .and(evictedAt.isNull)
                .and(evictionStartedAt.isNull.or(evictionStartedAt.lt(OffsetDateTime.now().minusMinutes(5))))
                .orderBy(MEDIA.DELETE_AT.asc())
                .limit(batchSize)
                .forUpdate()
                .skipLocked()
                .fetch()
            candidates.forEach { media ->
                tx.update(MEDIA)
                    .set(evictionStartedAt, OffsetDateTime.now())
                    .where(MEDIA.ID.eq(requireNotNull(media[MEDIA.ID])))
                    .execute()
            }
            candidates
        }
        candidates.forEach { media ->
            val mediaId = requireNotNull(media[MEDIA.ID])
            val deleted = gateway.get().evict(mediaId, requireNotNull(media[MEDIA.STORAGE_PATH]))
            if (deleted) markEvicted(mediaId) else recordFailure(mediaId)
        }
    }

    private fun markEvicted(mediaId: Long) {
        dsl.update(MEDIA)
            .set(evictedAt, OffsetDateTime.now())
            .where(MEDIA.ID.eq(mediaId))
            .and(evictedAt.isNull)
            .execute()
    }

    private fun recordFailure(mediaId: Long) {
        dsl.update(MEDIA)
            .set(deletionFailedAt, OffsetDateTime.now())
            .set(deletionAttempts, deletionAttempts.plus(1))
            .set(evictionStartedAt, null as OffsetDateTime?)
            .where(MEDIA.ID.eq(mediaId))
            .and(evictedAt.isNull)
            .execute()
    }

    private companion object {
        const val batchSize = 100
        val evictedAt = DSL.field(DSL.name("media", "evicted_at"), OffsetDateTime::class.java)
        val evictionStartedAt = DSL.field(DSL.name("media", "eviction_started_at"), OffsetDateTime::class.java)
        val deletionFailedAt = DSL.field(DSL.name("media", "deletion_failed_at"), OffsetDateTime::class.java)
        val deletionAttempts = DSL.field(DSL.name("media", "deletion_attempts"), Int::class.java)
    }
}
