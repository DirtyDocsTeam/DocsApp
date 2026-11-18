package ru.dirtydocs.api.media

import jakarta.enterprise.context.ApplicationScoped
import org.jooq.DSLContext
import ru.dirtydocs.api.generated.jooq.tables.references.MEDIA
import java.time.Duration
import java.time.OffsetDateTime

/** Extends the cache lease whenever an authorized workflow uses a media object. */
@ApplicationScoped
class MediaLeaseService(
    private val dsl: DSLContext,
) {
    fun touch(mediaId: Long, retention: Duration) {
        require(!retention.isNegative && !retention.isZero) { "Media retention must be positive" }
        val now = OffsetDateTime.now()
        dsl.update(MEDIA)
            .set(MEDIA.DELETE_AT, now.plus(retention))
            .where(MEDIA.ID.eq(mediaId))
            .execute()
    }
}
