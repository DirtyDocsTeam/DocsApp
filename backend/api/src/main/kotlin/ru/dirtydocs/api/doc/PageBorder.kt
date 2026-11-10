package ru.dirtydocs.api.doc

import kotlinx.serialization.Serializable

@Serializable
data class PageBorder(
    val leftValue: Float = 0f,
    val leftMeasure: Measurement = Measurement.CM,
    val rightValue: Float = 0f,
    val rightMeasure: Measurement = Measurement.CM,
    val topValue: Float = 0f,
    val topMeasure: Measurement = Measurement.CM,
    val bottomValue: Float = 0f,
    val bottomMeasure: Measurement = Measurement.CM,
)
