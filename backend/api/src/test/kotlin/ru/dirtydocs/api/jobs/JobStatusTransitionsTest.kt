package ru.dirtydocs.api.jobs

import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import ru.dirtydocs.api.jobs.requests.JobStatus

class JobStatusTransitionsTest {
    @Test
    fun queuesOnlyAfterEveryExpectedMediaIsReceived() {
        assertTrue(JobStatusTransitions.canTransition(JobStatus.WAITING_FOR_MEDIA, JobStatus.QUEUED))
        assertFalse(JobStatusTransitions.canTransition(JobStatus.WAITING_FOR_MEDIA, JobStatus.PROCESSING))
    }

    @Test
    fun allowsWorkersToSkipIrrelevantStages() {
        assertTrue(JobStatusTransitions.canTransition(JobStatus.QUEUED, JobStatus.VALIDATION))
        assertTrue(JobStatusTransitions.canTransition(JobStatus.PROCESSING, JobStatus.COMPLETED))
    }

    @Test
    fun rejectsLateReportsFromTerminalJobs() {
        JobStatusTransitions.terminal.forEach { terminal ->
            assertFalse(JobStatusTransitions.canTransition(terminal, JobStatus.PROCESSING))
            assertFalse(JobStatusTransitions.canTransition(terminal, JobStatus.COMPLETED))
        }
    }

    @Test
    fun cannotMoveProcessingBackToWaitingForMedia() {
        assertFalse(JobStatusTransitions.canTransition(JobStatus.PROCESSING, JobStatus.WAITING_FOR_MEDIA))
    }
}
