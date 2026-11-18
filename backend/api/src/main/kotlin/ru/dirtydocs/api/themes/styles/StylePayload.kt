package ru.dirtydocs.api.themes.styles

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/** Validates the temporary schema-agnostic style payload. */
object StylePayload {
    fun requireJsonObject(value: String): String {
        require(json.parseToJsonElement(value) is JsonObject) { "Style data must be a JSON object" }
        return value
    }

    private val json = Json { ignoreUnknownKeys = true }
}
