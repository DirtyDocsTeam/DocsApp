package ru.dirtydocs.api.doc

import kotlinx.serialization.Serializable

@Serializable
data class PageSize (
    val width: Float,
    val widthMeasure: Measurement,
    val height: Float,
    val heightMeasure: Measurement,
) {
    companion object {
        val A4 = PageSize(210f, Measurement.MM, 297f, Measurement.MM)
        val A5 = PageSize(148f, Measurement.MM, 210f, Measurement.MM)
        val A6 = PageSize(105f, Measurement.MM, 148f, Measurement.MM)
        val LETTER = PageSize(216f, Measurement.MM, 279f, Measurement.MM)
    }
}