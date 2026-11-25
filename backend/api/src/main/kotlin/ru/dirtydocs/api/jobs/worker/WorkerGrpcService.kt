package ru.dirtydocs.api.jobs.worker

import io.quarkus.grpc.GrpcService
import io.smallrye.mutiny.Uni
import ru.dirtydocs.api.jobs.AnnounceJobStatusRequest
import ru.dirtydocs.api.jobs.AnnounceJobStatusResponse
import ru.dirtydocs.api.jobs.JobStatusService
import ru.dirtydocs.api.jobs.MutinyWorkerServiceGrpc
import ru.dirtydocs.api.jobs.requests.JobStatus

/** Receives durable status announcements from workers assigned by Main API. */
@GrpcService
class WorkerGrpcService(
    private val jobStatuses: JobStatusService,
) : MutinyWorkerServiceGrpc.WorkerServiceImplBase() {
    override fun announceJobStatus(request: AnnounceJobStatusRequest): Uni<AnnounceJobStatusResponse> {
        val status = runCatching { JobStatus.fromDb(request.status) }.getOrNull()
        val accepted = request.jobId > 0 && request.deliveryKey.isNotBlank() && status != null &&
            jobStatuses.announce(request.jobId, status, request.deliveryKey)
        return Uni.createFrom().item(
            AnnounceJobStatusResponse.newBuilder().setAccepted(accepted).build(),
        )
    }
}
