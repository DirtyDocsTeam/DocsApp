package ru.dirtydocs.api.themes

import kotlinx.serialization.Serializable
import ru.dirtydocs.api.doc.PageParameters

@Serializable
data class ThemeParameters(
    val page: PageParameters = PageParameters()
)