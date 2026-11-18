package ru.dirtydocs.api.subscriptions

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.reactivestreams.Subscriber
import org.reactivestreams.Subscription
import ru.dirtydocs.api.jobs.requests.JobStatus
import java.time.OffsetDateTime
import java.util.concurrent.CopyOnWriteArrayList

class DomainEventPublisherTest {
    @Test
    fun jobSubscriptionOnlyReceivesTheSubscribersOwnJob() {
        val publisher = DomainEventPublisher()
        val received = CopyOnWriteArrayList<JobStatusChange>()
        publisher.jobChangesFor(userId = 1, jobId = "job-a").subscribe(collecting(received))

        publisher.publishJob(1, jobChange("job-a"))
        publisher.publishJob(2, jobChange("job-a"))
        publisher.publishJob(1, jobChange("job-b"))

        assertEquals(listOf(jobChange("job-a")), received)
    }

    @Test
    fun themeSubscriptionReceivesOwnAndPublicChangesOnly() {
        val publisher = DomainEventPublisher()
        val received = CopyOnWriteArrayList<ThemeChange>()
        publisher.themeChangesFor(userId = 1).subscribe(collecting(received))
        val mine = themeChange(1)
        val public = themeChange(2)

        publisher.publishTheme(1, isPublic = false, mine)
        publisher.publishTheme(2, isPublic = true, public)
        publisher.publishTheme(2, isPublic = false, themeChange(3))

        assertEquals(listOf(mine, public), received)
    }

    private fun jobChange(id: String) = JobStatusChange(id, JobStatus.QUEUED, OffsetDateTime.MIN)
    private fun themeChange(id: Long) = ThemeChange(id, ThemeChangeAction.UPDATED, OffsetDateTime.MIN)

    private fun <T> collecting(received: MutableList<T>) = object : Subscriber<T> {
        override fun onSubscribe(subscription: Subscription) = subscription.request(Long.MAX_VALUE)
        override fun onNext(item: T) {
            received.add(item)
        }
        override fun onError(throwable: Throwable) = throw AssertionError(throwable)
        override fun onComplete() = Unit
    }
}
