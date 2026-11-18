package ru.dirtydocs.api.themes.styles

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test

class StylePayloadTest {
    @Test
    fun preservesAnArbitraryJsonObject() {
        val payload = """{"font":{"family":"Inter"},"spacing":1.5}"""

        assertEquals(payload, StylePayload.requireJsonObject(payload))
    }

    @Test
    fun rejectsJsonScalarsAndArrays() {
        assertThrows(IllegalArgumentException::class.java) { StylePayload.requireJsonObject("[]") }
        assertThrows(IllegalArgumentException::class.java) { StylePayload.requireJsonObject("true") }
    }

    @Test
    fun rejectsInvalidJson() {
        assertThrows(IllegalArgumentException::class.java) { StylePayload.requireJsonObject("not-json") }
    }
}
