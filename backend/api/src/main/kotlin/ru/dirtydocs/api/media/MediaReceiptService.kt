package ru.dirtydocs.api.media

import jakarta.enterprise.context.ApplicationScoped
import org.jooq.DSLContext
import org.jooq.JSONB
import org.jooq.impl.DSL
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_MEDIA
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_REQUEST
import ru.dirtydocs.api.generated.jooq.tables.references.MEDIA
import ru.dirtydocs.api.jobs.requests.JobStatus
import ru.dirtydocs.api.subscriptions.DomainEventPublisher
import ru.dirtydocs.api.subscriptions.JobStatusChange
import java.time.Duration
import java.time.OffsetDateTime

/** Applies an idempotent Gateway receipt and queues every job whose declared media is complete. */
@ApplicationScoped
class MediaReceiptService(
    private val dsl: DSLContext,
    private val leases: MediaLeaseService,
    private val events: DomainEventPublisher,
) {
    fun confirmReceipt(
        userId: Long,
        hash: String,
        mimeType: String,
        storagePath: String,
        publicPath: String,
        receiptKey: String,
    ) {
        require(hash.isNotBlank() && receiptKey.isNotBlank())
        val outcome = dsl.transactionResult { configuration ->
            val tx = DSL.using(configuration)
            val queuedRequestIds = mutableListOf<Long>()
            val expectations = tx.select(expectedId, expectedRequestId, expectedRole)
                .from(expectedMedia)
                .where(expectedUserId.eq(userId))
                .and(expectedHash.eq(hash))
                .and(expectedState.eq(EXPECTED))
                .forUpdate()
                .fetch()
            if (expectations.isEmpty()) {
                val receivedRoles = tx.select(expectedRole)
                    .from(expectedMedia)
                    .where(expectedUserId.eq(userId))
                    .and(expectedHash.eq(hash))
                    .and(expectedState.eq(RECEIVED))
                    .and(expectedReceiptKey.eq(receiptKey))
                    .fetch(expectedRole)
                require(receivedRoles.isNotEmpty()) { "Media receipt was not expected" }
                return@transactionResult ReceiptOutcome(
                    if (receivedRoles.any { it == ATTACHMENT }) attachmentRetention else primaryRetention,
                    emptyList(),
                )
            }
            val mediaId = tx.select(MEDIA.ID).from(MEDIA)
                .where(MEDIA.FILE_HASH.eq(hash))
                .fetchOne(MEDIA.ID)
                ?: tx.insertInto(MEDIA)
                    .set(MEDIA.IS_NON_CACHEABLE, false)
                    .set(MEDIA.MIME_TYPE, mimeType)
                    .set(MEDIA.STORAGE_PATH, storagePath)
                    .set(MEDIA.FILE_HASH, hash)
                    .returning(MEDIA.ID)
                    .fetchOne(MEDIA.ID)
                ?: error("Media receipt did not return an id")
            expectations.forEach { expectation ->
                val requestId = requireNotNull(expectation.get(expectedRequestId))
                val role = requireNotNull(expectation.get(expectedRole))
                tx.update(expectedMedia)
                    .set(expectedState, RECEIVED)
                    .set(expectedMediaId, mediaId)
                    .set(expectedReceiptKey, receiptKey)
                    .where(expectedId.eq(requireNotNull(expectation.get(expectedId))))
                    .execute()
                tx.insertInto(JOB_MEDIA)
                    .set(JOB_MEDIA.REQUEST_ID, requestId)
                    .set(JOB_MEDIA.MEDIA_ID, mediaId)
                    .set(JOB_MEDIA.PUBLIC_PATH, publicPath)
                    .onConflictDoNothing()
                    .execute()
                if (role == PRIMARY) {
                    tx.update(JOB_REQUEST)
                        .set(JOB_REQUEST.PROCESSING_MEDIA_ID, mediaId)
                        .where(JOB_REQUEST.ID.eq(requestId))
                        .execute()
                }
                if (isComplete(tx, requestId)) {
                    val queued = tx.update(JOB_REQUEST)
                        .set(JOB_REQUEST.STATUS, JobStatus.QUEUED.dbValue)
                        .where(JOB_REQUEST.ID.eq(requestId))
                        .and(JOB_REQUEST.STATUS.eq(JobStatus.WAITING_FOR_MEDIA.dbValue))
                        .execute()
                    if (queued == 1) queuedRequestIds += requestId
                }
            }
            ReceiptOutcome(
                if (expectations.any { it.get(expectedRole) == ATTACHMENT }) attachmentRetention else primaryRetention,
                queuedRequestIds,
            )
        }
        val mediaId = dsl.select(MEDIA.ID).from(MEDIA).where(MEDIA.FILE_HASH.eq(hash)).fetchOne(MEDIA.ID)
        if (mediaId != null) leases.touch(mediaId, outcome.retention)
        if (outcome.queuedRequestIds.isNotEmpty()) {
            dsl.select(JOB_REQUEST.USER_ID, JOB_REQUEST.EXTERNAL_ID, JOB_REQUEST.UPDATED_AT)
                .from(JOB_REQUEST)
                .where(JOB_REQUEST.ID.`in`(outcome.queuedRequestIds))
                .fetch()
                .forEach { request ->
                    events.publishJob(
                        requireNotNull(request[JOB_REQUEST.USER_ID]),
                        JobStatusChange(
                            requireNotNull(request[JOB_REQUEST.EXTERNAL_ID]),
                            JobStatus.QUEUED,
                            requireNotNull(request[JOB_REQUEST.UPDATED_AT]),
                        ),
                    )
                }
        }
    }

    private fun isComplete(tx: DSLContext, requestId: Long): Boolean =
        tx.fetchExists(
            DSL.selectOne().from(expectedMedia)
                .where(expectedRequestId.eq(requestId))
                .and(expectedState.eq(EXPECTED))
        ).not()

    private companion object {
        const val EXPECTED = "expected"
        const val RECEIVED = "received"
        const val PRIMARY = "primary"
        const val ATTACHMENT = "attachment"
        val primaryRetention: Duration = Duration.ofHours(3)
        val attachmentRetention: Duration = Duration.ofDays(7)
        val expectedMedia = DSL.table(DSL.name("job_expected_media"))
        val expectedId = DSL.field(DSL.name("job_expected_media", "id"), Long::class.java)
        val expectedRequestId = DSL.field(DSL.name("job_expected_media", "request_id"), Long::class.java)
        val expectedUserId = DSL.field(DSL.name("job_expected_media", "user_id"), Long::class.java)
        val expectedHash = DSL.field(DSL.name("job_expected_media", "file_hash"), String::class.java)
        val expectedRole = DSL.field(DSL.name("job_expected_media", "role"), String::class.java)
        val expectedState = DSL.field(DSL.name("job_expected_media", "state"), String::class.java)
        val expectedMediaId = DSL.field(DSL.name("job_expected_media", "media_id"), Long::class.java)
        val expectedReceiptKey = DSL.field(DSL.name("job_expected_media", "receipt_key"), String::class.java)
    }

    private data class ReceiptOutcome(val retention: Duration, val queuedRequestIds: List<Long>)
}
