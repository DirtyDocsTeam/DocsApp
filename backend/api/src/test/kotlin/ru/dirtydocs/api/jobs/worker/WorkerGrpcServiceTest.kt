package ru.dirtydocs.api.jobs.worker

import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import ru.dirtydocs.api.jobs.AnnounceJobStatusRequest
import ru.dirtydocs.api.jobs.JobStatusService
import ru.dirtydocs.api.jobs.requests.JobStatus

class WorkerGrpcServiceTest {
    @Test
    fun rejectsUnknownStatusWithoutCallingTheJobService() {
        val statuses = mock(JobStatusService::class.java)
        val response = WorkerGrpcService(statuses).announceJobStatus(
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
        val response = WorkerGrpcService(statuses).announceJobStatus(
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
        `when`(statuses.announce(42, JobStatus.PROCESSING, "delivery")).thenReturn(true)
        val response = WorkerGrpcService(statuses).announceJobStatus(
            AnnounceJobStatusRequest.newBuilder()
                .setJobId(42)
                .setStatus(JobStatus.PROCESSING.dbValue)
                .setDeliveryKey("delivery")
                .build(),
        ).await().indefinitely()

        assertTrue(response.accepted)
        verify(statuses).announce(42, JobStatus.PROCESSING, "delivery")
    }
}
