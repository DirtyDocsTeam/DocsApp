package ru.dirtydocs.data

import org.jooq.impl.DSL
import org.jooq.SQLDialect
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ProjectionTest {
    @Test
    fun whereCombinesTheAdditionalConditionWithTheAccessCondition() {
        val table = DSL.table(DSL.name("items"))
        val id = DSL.field(DSL.name("items", "id"), Long::class.java)
        val visible = DSL.field(DSL.name("items", "visible"), Boolean::class.java)
        val category = DSL.field(DSL.name("items", "category"), String::class.java)
        val projection = Projection(
            table = table,
            id = id,
            nodes = columnNodes(mapOf("id" to id)),
            required = setOf("id"),
            factory = ViewFactory { _, _ -> Any() },
            access = { visible.eq(true) },
        )

        val selected = projection.compile(Selection.of("id"), ProjectionContext(viewerId = 1))
            .where(category.eq("personal"))
        val sql = DSL.using(SQLDialect.POSTGRES).renderInlined(selected.condition).uppercase()

        assertTrue(sql.contains("\"ITEMS\".\"VISIBLE\" = TRUE"))
        assertTrue(sql.contains("\"ITEMS\".\"CATEGORY\" = 'PERSONAL'"))
    }
}
