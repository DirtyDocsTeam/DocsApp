package ru.dirtydocs

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class ExampleResourceTest {
    @Test
    fun returnsGreeting() = assertEquals("Hello from Quarkus REST", ExampleResource().hello())

}
