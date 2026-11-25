package ru.dirtydocs.api.jobs.worker

import io.grpc.ManagedChannelBuilder
import io.smallrye.mutiny.Uni
import jakarta.enterprise.context.ApplicationScoped
import ru.dirtydocs.api.jobs.AssignJobRequest
import ru.dirtydocs.api.jobs.MutinyWorkerServiceGrpc
import java.util.concurrent.TimeUnit

/** Sends an assignment over TLS to the endpoint most recently announced by a worker. */
@ApplicationScoped
class WorkerAssignmentClient {
    fun assign(worker: RegisteredWorker, jobId: Long, deliveryKey: String): Uni<Boolean> {
        val channel = ManagedChannelBuilder.forAddress(worker.host, worker.port).build()
        return MutinyWorkerServiceGrpc.newMutinyStub(channel)
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
            .onTermination()
            .invoke(channel::shutdown)
    }
}
