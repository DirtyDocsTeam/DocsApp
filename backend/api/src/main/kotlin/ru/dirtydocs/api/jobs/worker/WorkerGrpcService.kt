package ru.dirtydocs.api.jobs.worker

import io.quarkus.grpc.GrpcService
import io.smallrye.mutiny.Uni
import ru.dirtydocs.api.jobs.AnnounceWorkerRequest
import ru.dirtydocs.api.jobs.AnnounceWorkerResponse
import ru.dirtydocs.api.jobs.AnnounceJobStatusRequest
import ru.dirtydocs.api.jobs.AnnounceJobStatusResponse
import ru.dirtydocs.api.jobs.JobStatusService
import ru.dirtydocs.api.jobs.MutinyWorkerServiceGrpc
import ru.dirtydocs.api.jobs.requests.JobStatus

/** Receives durable status announcements from workers assigned by Main API. */
@GrpcService
class WorkerGrpcService(
    private val jobStatuses: JobStatusService,
    private val workerAnnouncements: WorkerAnnouncementController,
) : MutinyWorkerServiceGrpc.WorkerServiceImplBase() {
    override fun announceWorker(request: AnnounceWorkerRequest): Uni<AnnounceWorkerResponse> {
        val accepted = request.workerId.isNotBlank() && request.host.isNotBlank() && request.port in 1..65535
        if (accepted) {
            workerAnnouncements.announce(request.workerId, request.host, request.port)
        }
        return Uni.createFrom().item(
            AnnounceWorkerResponse.newBuilder().setAccepted(accepted).build(),
        )
    }

    override fun announceJobStatus(request: AnnounceJobStatusRequest): Uni<AnnounceJobStatusResponse> {
        val status = runCatching { JobStatus.fromDb(request.status) }.getOrNull()
        val accepted = request.jobId > 0 && request.deliveryKey.isNotBlank() && status != null &&
            jobStatuses.announce(request.jobId, status, request.deliveryKey)
        return Uni.createFrom().item(
            AnnounceJobStatusResponse.newBuilder().setAccepted(accepted).build(),
        )
    }
}
