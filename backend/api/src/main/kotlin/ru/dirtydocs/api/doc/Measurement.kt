package ru.dirtydocs.api.doc

import kotlinx.serialization.Serializable

enum class Measurement(val value: String) {
    MM("mm"),
    CM("cm"),
    INCH("inch"),
    PT("pt"),
    PX("px");
}