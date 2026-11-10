package ru.dirtydocs.api.users.tokens.access

import kotlinx.serialization.Serializable

@Serializable
data class TokenAccessRights(
    val userData: AccessPermissions = AccessPermissions(),
    val apiTokens: AccessPermissions = AccessPermissions(),
    val jobs: AccessPermissions = AccessPermissions(),
    val themes: AccessPermissions = AccessPermissions()
) {
}