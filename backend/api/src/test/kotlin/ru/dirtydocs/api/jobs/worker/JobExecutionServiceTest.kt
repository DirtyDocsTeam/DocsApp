package ru.dirtydocs.api.jobs.worker

import org.jooq.DSLContext
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.mockito.Mockito.mock
import ru.dirtydocs.api.jobs.requests.JobType

class JobExecutionServiceTest {
    @Test
    fun recordsTheEndpointAnnouncedByAWorker() {
        val execution = RegistryOnlyJobExecutionService(
            mock(DSLContext::class.java),
            mock(WorkerAssignmentClient::class.java),
        )

        execution.registerWorker(
            "conversion-1",
            "worker.internal",
            9000,
            setOf(JobType.CONVERSION),
        )

        val worker = requireNotNull(execution.worker("conversion-1"))
        assertEquals("worker.internal", worker.host)
        assertEquals(9000, worker.port)
        assertEquals(setOf(JobType.CONVERSION), worker.supportedJobTypes)
    }

    @Test
    fun returnsOnlyWorkersThatSupportTheRequestedJobType() {
        val execution = RegistryOnlyJobExecutionService(
            mock(DSLContext::class.java),
            mock(WorkerAssignmentClient::class.java),
        )
        execution.registerWorker("conversion-1", "conversion.internal", 9000, setOf(JobType.CONVERSION))
        execution.registerWorker("validation-1", "validation.internal", 9001, setOf(JobType.VALIDATION))

        assertEquals(listOf("validation-1"), execution.registeredWorkersFor(JobType.VALIDATION).map { it.id })
    }

    private class RegistryOnlyJobExecutionService(
        dsl: DSLContext,
        workerAssignments: WorkerAssignmentClient,
    ) : JobExecutionService(dsl, workerAssignments) {
        override fun dispatchQuery(): Long = 0
    }
}
