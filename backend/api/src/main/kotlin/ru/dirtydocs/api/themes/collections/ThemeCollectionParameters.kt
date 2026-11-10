package ru.dirtydocs.api.themes.collections

import kotlinx.serialization.Serializable

@Serializable
data class ThemeCollectionParameters(
    val todo: Long
)
