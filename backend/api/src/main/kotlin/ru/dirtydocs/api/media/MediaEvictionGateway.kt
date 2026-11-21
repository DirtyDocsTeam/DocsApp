package ru.dirtydocs.api.media

/**
 * Internal S3 Gateway boundary for deletion of an expired media object.
 *
 * TODO: provide an mTLS gRPC implementation when Main API ↔ S3 Gateway
 * connectivity is deployed. The storage path never crosses a client boundary.
 */
interface MediaEvictionGateway {
    fun evict(mediaId: Long, storagePath: String): Boolean
}
