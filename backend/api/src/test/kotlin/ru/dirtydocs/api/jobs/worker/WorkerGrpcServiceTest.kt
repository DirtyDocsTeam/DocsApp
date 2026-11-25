package ru.dirtydocs.api.jobs.worker

import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import ru.dirtydocs.api.jobs.AnnounceJobStatusRequest
import ru.dirtydocs.api.jobs.AnnounceWorkerRequest
import ru.dirtydocs.api.jobs.JobStatusService
import ru.dirtydocs.api.jobs.requests.JobStatus
import ru.dirtydocs.api.jobs.requests.JobType

class WorkerGrpcServiceTest {
    @Test
    fun rejectsUnknownStatusWithoutCallingTheJobService() {
        val statuses = mock(JobStatusService::class.java)
        val execution = mock(JobExecutionService::class.java)
        val response = WorkerGrpcService(statuses, execution).announceJobStatus(
            AnnounceJobStatusRequest.newBuilder()
                .setJobId(42)
                .setStatus("unknown")
                .setDeliveryKey("delivery")
                .build(),
        ).await().indefinitely()

        assertFalse(response.accepted)
        verifyNoInteractions(statuses)
    }

    @Test
    fun rejectsAnAnnouncementWithoutADeliveryKey() {
        val statuses = mock(JobStatusService::class.java)
        val execution = mock(JobExecutionService::class.java)
        val response = WorkerGrpcService(statuses, execution).announceJobStatus(
            AnnounceJobStatusRequest.newBuilder()
                .setJobId(42)
                .setStatus(JobStatus.PROCESSING.dbValue)
                .build(),
        ).await().indefinitely()

        assertFalse(response.accepted)
        verifyNoInteractions(statuses)
    }

    @Test
    fun forwardsValidAnnouncementWithItsDeliveryKey() {
        val statuses = mock(JobStatusService::class.java)
        val execution = mock(JobExecutionService::class.java)
        `when`(statuses.announce(42, JobStatus.PROCESSING, "delivery")).thenReturn(true)
        val response = WorkerGrpcService(statuses, execution).announceJobStatus(
            AnnounceJobStatusRequest.newBuilder()
                .setJobId(42)
                .setStatus(JobStatus.PROCESSING.dbValue)
                .setDeliveryKey("delivery")
                .build(),
        ).await().indefinitely()

        assertTrue(response.accepted)
        verify(statuses).announce(42, JobStatus.PROCESSING, "delivery")
    }

    @Test
    fun recordsAWorkerAnnouncement() {
        val statuses = mock(JobStatusService::class.java)
        val execution = mock(JobExecutionService::class.java)
        val response = WorkerGrpcService(statuses, execution).announceWorker(
            AnnounceWorkerRequest.newBuilder()
                .setWorkerId("conversion-1")
                .setHost("worker.internal")
                .setPort(9000)
                .addSupportedJobTypes(JobType.CONVERSION.dbValue)
                .build(),
        ).await().indefinitely()

        assertTrue(response.accepted)
        verify(execution).registerWorker(
            "conversion-1",
            "worker.internal",
            9000,
            setOf(JobType.CONVERSION),
        )
    }

    @Test
    fun rejectsWorkerAnnouncementWithoutAReachableEndpoint() {
        val statuses = mock(JobStatusService::class.java)
        val execution = mock(JobExecutionService::class.java)
        val response = WorkerGrpcService(statuses, execution).announceWorker(
            AnnounceWorkerRequest.newBuilder()
                .setWorkerId("conversion-1")
                .setHost("worker.internal")
                .addSupportedJobTypes(JobType.CONVERSION.dbValue)
                .build(),
        ).await().indefinitely()

        assertFalse(response.accepted)
        verifyNoInteractions(execution)
    }

    @Test
    fun rejectsWorkerAnnouncementWithAnUnknownJobType() {
        val statuses = mock(JobStatusService::class.java)
        val execution = mock(JobExecutionService::class.java)
        val response = WorkerGrpcService(statuses, execution).announceWorker(
            AnnounceWorkerRequest.newBuilder()
                .setWorkerId("conversion-1")
                .setHost("worker.internal")
                .setPort(9000)
                .addSupportedJobTypes("unknown")
                .build(),
        ).await().indefinitely()

        assertFalse(response.accepted)
        verifyNoInteractions(execution)
    }
}
