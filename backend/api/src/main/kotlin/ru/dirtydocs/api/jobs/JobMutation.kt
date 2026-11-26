package ru.dirtydocs.api.jobs

import graphql.schema.DataFetchingEnvironment
import jakarta.enterprise.inject.Instance
import jakarta.ws.rs.ClientErrorException
import jakarta.ws.rs.core.Response
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.eclipse.microprofile.graphql.Description
import org.eclipse.microprofile.graphql.GraphQLApi
import org.eclipse.microprofile.graphql.Mutation
import org.jooq.DSLContext
import org.jooq.JSONB
import org.jooq.impl.DSL
import ru.dirtydocs.api.auth.ApiTokenAccessAuthorizer
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_MEDIA
import ru.dirtydocs.api.generated.jooq.tables.references.JOB_REQUEST
import ru.dirtydocs.api.generated.jooq.tables.references.MEDIA
import ru.dirtydocs.api.jobs.requests.JobRequest
import ru.dirtydocs.api.jobs.requests.JobStatus
import ru.dirtydocs.api.jobs.worker.JobExecutionService
import ru.dirtydocs.api.media.MediaLeaseService
import ru.dirtydocs.api.subscriptions.DomainEventPublisher
import ru.dirtydocs.api.subscriptions.JobStatusChange
import ru.dirtydocs.api.themes.ThemeProjections
import ru.dirtydocs.data.ProjectionContext
import ru.dirtydocs.data.Selection
import java.time.Duration
import java.time.OffsetDateTime
import java.security.MessageDigest
import java.util.HexFormat
import java.util.UUID

/** Creates an idempotent job that waits until every declared content hash is available. */
@GraphQLApi
class JobMutation(
    private val contexts: Instance<ProjectionContext>,
    private val dsl: DSLContext,
    private val tokenAccess: ApiTokenAccessAuthorizer,
    private val events: DomainEventPublisher,
    private val leases: MediaLeaseService,
    private val execution: JobExecutionService,
) {
    @Mutation
    @Description("Create a job and report media hashes that the gateway must upload")
    fun createJob(env: DataFetchingEnvironment, input: CreateJobInput): CreateJobResult {
        tokenAccess.requireEdit { it.jobs }
        val context = contexts.get()
        val viewerId = context.viewerId ?: throw ClientErrorException(Response.Status.UNAUTHORIZED)
        val hashes = linkedSetOf(input.primaryMediaHash.trim()).apply { addAll(input.attachmentMediaHashes.map(String::trim)) }
        require(hashes.none(String::isEmpty)) { "Media hashes must not be blank" }
        require(input.idempotencyKey.isNotBlank()) { "Idempotency key must not be blank" }
        val fingerprint = input.fingerprint(hashes)
        requireNotNull(ThemeProjections.THEME.fetchById(dsl, input.themeId, Selection.of("id"), context)) {
            "Theme is not visible"
        }

        val existing = dsl.select(JOB_REQUEST.ID, requestFingerprint)
            .from(JOB_REQUEST)
            .where(JOB_REQUEST.USER_ID.eq(viewerId))
            .and(idempotencyKey.eq(input.idempotencyKey))
            .fetchOne()
        if (existing != null && existing[requestFingerprint] != fingerprint) {
            throw ClientErrorException(Response.Status.CONFLICT)
        }
        val jobId = existing?.get(JOB_REQUEST.ID) ?: dsl.transactionResult { configuration ->
            val tx = DSL.using(configuration)
            val cachedMedia = tx.select(MEDIA.ID, MEDIA.FILE_HASH)
                .from(MEDIA)
                .where(MEDIA.FILE_HASH.`in`(hashes))
                .fetchMap(MEDIA.FILE_HASH, MEDIA.ID)
            val createdId = tx.insertInto(JOB_REQUEST)
                .set(JOB_REQUEST.EXTERNAL_ID, UUID.randomUUID().toString())
                .set(JOB_REQUEST.INPUT_TYPE, input.inputType)
                .set(JOB_REQUEST.OUTPUT_TYPE, input.outputType)
                .set(JOB_REQUEST.TYPE, input.type.dbValue)
                .set(
                    JOB_REQUEST.STATUS,
                    if (cachedMedia.size == hashes.size) JobStatus.QUEUED.dbValue else JobStatus.WAITING_FOR_MEDIA.dbValue,
                )
                .set(JOB_REQUEST.USER_ID, viewerId)
                .set(JOB_REQUEST.THEME_ID, input.themeId)
                .set(JOB_REQUEST.PARAMETERS, JSONB.valueOf(json.encodeToString(input.parameters)))
                .set(idempotencyKey, input.idempotencyKey)
                .set(requestFingerprint, fingerprint)
                .returning(JOB_REQUEST.ID)
                .fetchOne(JOB_REQUEST.ID)
                ?: error("Job creation did not return an id")
            hashes.forEach { hash ->
                val role = if (hash == input.primaryMediaHash) PRIMARY else ATTACHMENT
                val mediaId = cachedMedia[hash]
                tx.insertInto(expectedMedia)
                    .set(expectedRequestId, createdId)
                    .set(expectedUserId, viewerId)
                    .set(expectedHash, hash)
                    .set(expectedRole, role)
                    .set(expectedState, if (mediaId == null) EXPECTED else RECEIVED)
                    .set(expectedMediaId, mediaId)
                    .set(expectedExpiresAt, OffsetDateTime.now().plusHours(1))
                    .execute()
                if (mediaId != null) {
                    tx.insertInto(JOB_MEDIA)
                        .set(JOB_MEDIA.REQUEST_ID, createdId)
                        .set(JOB_MEDIA.MEDIA_ID, mediaId)
                        .set(JOB_MEDIA.PUBLIC_PATH, UUID.randomUUID().toString())
                        .execute()
                    if (role == PRIMARY) {
                        tx.update(JOB_REQUEST)
                            .set(JOB_REQUEST.PROCESSING_MEDIA_ID, mediaId)
                            .where(JOB_REQUEST.ID.eq(createdId))
                            .execute()
                    }
                }
            }
            createdId
        }
        val availableMedia = dsl.select(MEDIA.ID, MEDIA.FILE_HASH)
            .from(MEDIA)
            .where(MEDIA.FILE_HASH.`in`(hashes))
            .fetchMap(MEDIA.FILE_HASH, MEDIA.ID)
        availableMedia.forEach { (hash, mediaId) ->
            leases.touch(requireNotNull(mediaId), if (hash == input.primaryMediaHash) primaryRetention else attachmentRetention)
        }
        val job = JobProjections.REQUEST.select(env, context).fetchById(dsl, jobId)
            ?: error("Created job is not visible to its owner")
        events.publishJob(viewerId, JobStatusChange(job.id, job.status, job.updatedAt))
        return CreateJobResult(job, hashes.filterNot(availableMedia::containsKey))
    }

    @Mutation
    @Description("Logically delete a current user's job and cancel it when it is not terminal")
    fun deleteJob(externalId: String): Boolean {
        tokenAccess.requireDelete { it.jobs }
        val owner = JOB_REQUEST.EXTERNAL_ID.eq(externalId).and(JOB_REQUEST.USER_ID.eq(requireViewer()))
        val cancelled = dsl.update(JOB_REQUEST)
            .set(deletedAt, OffsetDateTime.now())
            .set(JOB_REQUEST.STATUS, JobStatus.CANCELLED.dbValue)
            .where(owner.and(deletedAt.isNull).and(JOB_REQUEST.STATUS.notIn(terminalStatuses)))
            .returning(JOB_REQUEST.ID)
            .fetchOne(JOB_REQUEST.ID)
        if (cancelled != null) {
            execution.freeWorkerJob(cancelled)
            events.publishJob(requireViewer(), JobStatusChange(externalId, JobStatus.CANCELLED, OffsetDateTime.now()))
            return true
        }
        return dsl.update(JOB_REQUEST)
            .set(deletedAt, OffsetDateTime.now())
            .where(owner.and(deletedAt.isNull).and(JOB_REQUEST.STATUS.`in`(terminalStatuses)))
            .execute() == 1
    }

    private fun requireViewer(): Long = contexts.get().viewerId
        ?: throw ClientErrorException(Response.Status.UNAUTHORIZED)

    private fun CreateJobInput.fingerprint(hashes: Set<String>): String {
        val value = listOf(
            primaryMediaHash.trim(),
            hashes.sorted().joinToString(","),
            inputType,
            outputType,
            type.dbValue,
            themeId.toString(),
            json.encodeToString(parameters),
        ).joinToString("\u0000")
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.toByteArray()))
    }

    private companion object {
        val json = Json { ignoreUnknownKeys = true }
        val idempotencyKey = DSL.field(DSL.name("job_request", "idempotency_key"), String::class.java)
        val requestFingerprint = DSL.field(DSL.name("job_request", "request_fingerprint"), String::class.java)
        val deletedAt = DSL.field(DSL.name("job_request", "deleted_at"), OffsetDateTime::class.java)
        val terminalStatuses = listOf(
            JobStatus.COMPLETED.dbValue,
            JobStatus.COMPLETED_WITH_WARNINGS.dbValue,
            JobStatus.FAILED.dbValue,
            JobStatus.VALIDATION_FAILED.dbValue,
            JobStatus.CANCELLED.dbValue,
        )
        val expectedMedia = DSL.table(DSL.name("job_expected_media"))
        val expectedRequestId = DSL.field(DSL.name("job_expected_media", "request_id"), Long::class.java)
        val expectedUserId = DSL.field(DSL.name("job_expected_media", "user_id"), Long::class.java)
        val expectedHash = DSL.field(DSL.name("job_expected_media", "file_hash"), String::class.java)
        val expectedRole = DSL.field(DSL.name("job_expected_media", "role"), String::class.java)
        val expectedState = DSL.field(DSL.name("job_expected_media", "state"), String::class.java)
        val expectedMediaId = DSL.field(DSL.name("job_expected_media", "media_id"), Long::class.java)
        val expectedExpiresAt = DSL.field(DSL.name("job_expected_media", "expires_at"), OffsetDateTime::class.java)
        const val EXPECTED = "expected"
        const val RECEIVED = "received"
        const val PRIMARY = "primary"
        const val ATTACHMENT = "attachment"
        val primaryRetention: Duration = Duration.ofHours(3)
        val attachmentRetention: Duration = Duration.ofDays(7)
    }
}
