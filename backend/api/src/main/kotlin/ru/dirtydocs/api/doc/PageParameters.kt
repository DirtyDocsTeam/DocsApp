package ru.dirtydocs.api.doc

import kotlinx.serialization.Serializable

@Serializable
data class PageParameters(
    val border: PageBorder = PageBorder(),
    val pageSize: PageSize = PageSize.A4,
    val pageOrientation: PageOrientation = PageOrientation.PORTRAIT
)
