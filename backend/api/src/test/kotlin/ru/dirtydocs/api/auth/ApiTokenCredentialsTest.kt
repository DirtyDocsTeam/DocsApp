package ru.dirtydocs.api.auth

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test

class ApiTokenCredentialsTest {
    @Test
    fun parsesOpaqueApiToken() {
        val token = ApiTokenCredentials.parse("ddat_42_short")

        requireNotNull(token)
        assertEquals(42, token.id)
        assertEquals("short", token.secret)
        assertEquals("ApiTokenCredentials(id=42, secret=[redacted])", token.toString())
    }

    @Test
    fun rejectsJwtAndMalformedApiTokens() {
        assertNull(ApiTokenCredentials.parse("header.payload.signature"))
        assertNull(ApiTokenCredentials.parse("ddat_0_secret"))
        assertNull(ApiTokenCredentials.parse("ddat_42_"))
    }
}
