package ru.dirtydocs.api.users.tokens.access

import kotlinx.serialization.Serializable

@Serializable
data class AccessPermissions(
    val read: Boolean = false,
    val edit: Boolean = false,
    val delete: Boolean = false
)