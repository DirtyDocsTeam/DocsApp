package ru.dirtydocs.api.doc

import kotlinx.serialization.Serializable

@Serializable
data class PageBorder(
    val left: Float = 0f,
    val leftMeasure: Measurement = Measurement.CM,
    val right: Float = 0f,
    val rightMeasure: Measurement = Measurement.CM,
    val top: Float = 0f,
    val topMeasure: Measurement = Measurement.CM,
    val bottom: Float = 0f,
    val bottomMeasure: Measurement = Measurement.CM,
)
