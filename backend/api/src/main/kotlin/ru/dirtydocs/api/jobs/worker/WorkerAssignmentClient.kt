package ru.dirtydocs.api.jobs.worker

import io.quarkus.grpc.GrpcClient
import io.smallrye.mutiny.Uni
import jakarta.enterprise.context.ApplicationScoped
import ru.dirtydocs.api.jobs.AssignJobRequest
import ru.dirtydocs.api.jobs.MutinyWorkerServiceGrpc
import java.util.concurrent.TimeUnit

/** Sends an assignment to the configured worker pool with a bounded deadline. */
@ApplicationScoped
class WorkerAssignmentClient(
    @GrpcClient("worker") private val worker: MutinyWorkerServiceGrpc.MutinyWorkerServiceStub,
) {
    fun assign(jobId: Long, deliveryKey: String): Uni<Boolean> = worker
        .withDeadlineAfter(10, TimeUnit.SECONDS)
        .assignJob(
            AssignJobRequest.newBuilder()
                .setJobId(jobId)
                .setDeliveryKey(deliveryKey)
                .build(),
        )
        .onItem()
        .transform { it.accepted }
        .onFailure()
        .recoverWithItem(false)
}
