package ru.novari.data

import graphql.schema.DataFetchingEnvironment
import graphql.schema.DataFetchingFieldSelectionSet
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json
import org.jooq.Condition
import org.jooq.DSLContext
import org.jooq.Field
import org.jooq.JSONB
import org.jooq.Record
import org.jooq.SortField
import org.jooq.Table
import org.jooq.impl.DSL

/** Trusted request context; never populate viewerId from client-provided arguments. */
data class ProjectionContext(
    val viewerId: Long?,
    val maxDepth: Int = 6,
)

/** The single, transport-independent representation of a field selection. */
data class Selection(
    val fields: Map<String, Selection> = emptyMap(),
    val arguments: Map<String, Any?> = emptyMap(),
) {
    companion object {
        fun of(vararg names: String): Selection =
            Selection(names.associateWith { Selection() })
    }

    fun intArgument(name: String, default: Int): Int {
        val input = arguments[name] ?: return default
        require(input is Number) { "Argument '$name' must be numeric" }
        val result = input.toLong()
        require(result in Int.MIN_VALUE..Int.MAX_VALUE && input.toDouble() == result.toDouble()) {
            "Argument '$name' must be an integer in Int range"
        }
        return result.toInt()
    }
}

/**
 * GraphQL adapter. Rejects repeated underlying fields (including distinct aliases) rather than
 * accidentally combining different arguments. GraphQL fragments can create such repetitions;
 * adapt this function to your response-name semantics if your schema needs them.
 */
fun DataFetchingFieldSelectionSet.toSelection(): Selection {
    val selected = linkedMapOf<String, Selection>()
    for (field in getImmediateFields()) {
        require(field.name !in selected) {
            "GraphQL field '${field.name}' was selected more than once; " +
                    "merge/alias handling requires a dedicated adapter"
        }
        selected[field.name] = Selection(
            fields = field.selectionSet.toSelection().fields,
            arguments = field.arguments,
        )
    }
    return Selection(selected)
}

/** Field names refer to output-model properties, not DB columns or aliases. */
class ProjectionFields internal constructor(
    private val indexes: Map<String, Int>,
    private val objects: Map<String, ProjectionFields> = emptyMap(),
) {
    fun contains(name: String): Boolean = name in indexes || name in objects
    fun index(name: String): Int = indexes[name]
        ?: error("Scalar or relation field '$name' was not selected")
    fun embedded(name: String): ProjectionFields = objects[name]
        ?: error("Embedded field '$name' was not selected")
}

/** A read-only API. The underlying jOOQ Record is mutable: do not modify it after wrapping. */
open class RecordView(
    private val record: Record,
    private val fields: ProjectionFields,
) {
    fun has(name: String): Boolean = fields.contains(name)

    @Suppress("UNCHECKED_CAST")
    protected fun <T> value(name: String): T = record.get(fields.index(name)) as T

    protected fun <T : Any> required(name: String): T =
        requireNotNull(value<T?>(name)) { "Selected field '$name' contains null" }

    protected fun <T : Any> embedded(name: String, factory: ViewFactory<T>): T =
        factory.create(record, fields.embedded(name))
}

fun interface ViewFactory<T : Any> {
    fun create(record: Record, fields: ProjectionFields): T
}

/** No SQL is executed during wrapping. */
sealed interface ProjectionNode

data class ColumnNode(val expression: Field<*>) : ProjectionNode

fun column(expression: Field<*>): ProjectionNode = ColumnNode(expression)
fun columnNodes(mappings: Map<String, Field<*>>): Map<String, ProjectionNode> =
    mappings.mapValues { (_, value) -> ColumnNode(value) }

interface RelationNode : ProjectionNode {
    fun compile(selection: Selection, context: ProjectionContext, depth: Int): Field<*>
}

/** Flattened nested object on the same SQL row; no JOIN or separate SQL query. */
class EmbeddedNode(val nodes: Map<String, ProjectionNode>) : ProjectionNode

fun embedded(vararg fields: Pair<String, ProjectionNode>): EmbeddedNode =
    EmbeddedNode(linkedMapOf(*fields))

fun embedded(fields: Map<String, ProjectionNode>): EmbeddedNode = EmbeddedNode(fields)

private data class ColumnPlan(
    val expressions: List<Field<*>>,
    val mappings: ProjectionFields,
)

/**
 * Recursively flatten embedded objects. Relation nodes produce one SQL expression each
 * (usually a converted MULTISET), while embedded nodes share the same parent record.
 */
private fun compileColumns(
    nodes: Map<String, ProjectionNode>,
    selection: Selection,
    required: Set<String>,
    context: ProjectionContext,
    depth: Int,
    offset: Int = 0,
): ColumnPlan {
    require(depth <= context.maxDepth) { "Maximum projection depth exceeded" }

    val requested = linkedSetOf<String>().apply {
        addAll(required)
        addAll(selection.fields.keys)
    }
    val expressions = arrayListOf<Field<*>>()
    val indexes = linkedMapOf<String, Int>()
    val embeddedFields = linkedMapOf<String, ProjectionFields>()

    for (name in requested) {
        val node = nodes[name] ?: error("Field '$name' is not exposed by projection")
        val child = selection.fields[name] ?: Selection()
        when (node) {
            is ColumnNode -> {
                require(child.fields.isEmpty()) { "Scalar '$name' cannot have child fields" }
                indexes[name] = offset + expressions.size
                expressions += node.expression
            }
            is RelationNode -> {
                indexes[name] = offset + expressions.size
                expressions += node.compile(child, context, depth + 1)
            }
            is EmbeddedNode -> {
                require(child.arguments.isEmpty()) { "Embedded '$name' does not accept arguments" }
                val nested = compileColumns(
                    node.nodes, child, emptySet(), context,
                    depth + 1, offset + expressions.size,
                )
                embeddedFields[name] = nested.mappings
                expressions += nested.expressions
            }
        }
    }
    return ColumnPlan(expressions, ProjectionFields(indexes, embeddedFields))
}

/** A compiled, request-scoped query plan; keeps SQL positions and read-only mapping aligned. */
class SelectedProjection<T : Any> internal constructor(
    val table: Table<*>,
    val id: Field<Long?>,
    val condition: Condition,
    val fields: List<Field<*>>,
    private val mapping: ProjectionFields,
    private val factory: ViewFactory<T>,
) {
    fun wrap(record: Record): T = factory.create(record, mapping)

    /** Adds a caller-supplied predicate without bypassing the projection's access condition. */
    fun where(additionalCondition: Condition): SelectedProjection<T> =
        SelectedProjection(table, id, condition.and(additionalCondition), fields, mapping, factory)

    fun fetchById(dsl: DSLContext, value: Long): T? =
        dsl.select(fields).from(table)
            .where(condition).and(id.eq(value))
            .fetchOne()?.let(::wrap)

    fun fetchByIds(dsl: DSLContext, ids: Collection<Long>): List<T> {
        if (ids.isEmpty()) return emptyList()
        return dsl.select(fields).from(table)
            .where(condition).and(id.`in`(ids))
            .fetch().map(::wrap)
    }

    fun fetchPage(
        dsl: DSLContext,
        orderBy: List<SortField<*>>,
        limit: Int = 20,
        offset: Int = 0,
    ): List<T> {
        require(limit in 1..100 && offset >= 0)
        require(orderBy.isNotEmpty()) { "Page queries require deterministic order" }
        return dsl.select(fields).from(table)
            .where(condition).orderBy(orderBy)
            .limit(limit).offset(offset).fetch().map(::wrap)
    }
}

/**
 * The only reusable projection definition. Authorization is always supplied explicitly;
 * for sensitive projections prefer deny-by-default conditions.
 */
class Projection<T : Any>(
    val table: Table<*>,
    val id: Field<Long?>,
    private val nodes: Map<String, ProjectionNode>,
    private val factory: ViewFactory<T>,
    private val access: (ProjectionContext) -> Condition,
    private val required: Set<String> = emptySet(),
) {
    init {
        require(required.all { nodes[it] is ColumnNode }) {
            "Required fields must be scalar"
        }
    }

    fun select(env: DataFetchingEnvironment, context: ProjectionContext): SelectedProjection<T> =
        compile(env.selectionSet.toSelection(), context)

    fun compile(
        selection: Selection,
        context: ProjectionContext,
        depth: Int = 0,
    ): SelectedProjection<T> {
        val plan = compileColumns(nodes, selection, required, context, depth)
        require(plan.expressions.isNotEmpty()) { "Projection cannot select zero SQL fields" }
        return SelectedProjection(table, id, access(context), plan.expressions, plan.mappings, factory)
    }

    fun fetchById(
        dsl: DSLContext,
        value: Long,
        selection: Selection,
        context: ProjectionContext,
    ): T? = compile(selection, context).fetchById(dsl, value)

    /**
     * Wrap a trusted, already-loaded internal jOOQ Record without SQL.
     * Access checks MUST have happened in the calling code.
     * Computed fields may not exist on that record; only identical jOOQ Field keys are matched.
     */
    fun wrapInternal(record: Record, selection: Selection): T {
        val requested = linkedSetOf<String>().apply {
            addAll(required)
            addAll(selection.fields.keys)
        }
        val available = record.fields().toList()
        val indexes = linkedMapOf<String, Int>()
        val objects = linkedMapOf<String, ProjectionFields>()

        fun resolve(
            registry: Map<String, ProjectionNode>,
            selected: Set<String>,
            selections: Map<String, Selection>,
        ): ProjectionFields {
            val scalar = linkedMapOf<String, Int>()
            val embedded = linkedMapOf<String, ProjectionFields>()
            for (name in selected) {
                when (val node = registry[name] ?: error("Unknown field '$name'")) {
                    is ColumnNode -> {
                        val position = available.indexOf(node.expression)
                        require(position >= 0) { "Internal Record does not contain '$name'" }
                        scalar[name] = position
                    }
                    is EmbeddedNode -> {
                        val child = selections[name] ?: Selection()
                        embedded[name] = resolve(
                            node.nodes, child.fields.keys, child.fields,
                        )
                    }
                    is RelationNode -> error(
                        "Relationship '$name' must be fetched using a projection"
                    )
                }
            }
            return ProjectionFields(scalar, embedded)
        }
        val mapping = resolve(nodes, requested, selection.fields)
        return factory.create(record, mapping)
    }
}

/** N:1 or 1:1. Child definition is resolved only if the relation is selected. */
class OneRelation<C : Any>(
    private val childProvider: () -> Projection<C>,
    private val parentForeignKey: Field<Long?>,
    private val childKey: (Projection<C>) -> Field<Long?> = { it.id },
) : RelationNode {
    override fun compile(
        selection: Selection,
        context: ProjectionContext,
        depth: Int,
    ): Field<*> {
        val child = childProvider()
        val compiled = child.compile(selection, context, depth)
        val query = DSL.select(compiled.fields).from(child.table)
            .where(compiled.condition)
            .and(childKey(child).eq(parentForeignKey))
            .limit(1)
        return DSL.multiset(query).convertFrom { rows ->
            rows.firstOrNull()?.let(compiled::wrap)
        }
    }
}

/** 1:N; relation metadata, including aliased foreign key, is resolved lazily. */
class ManyRelation<C : Any>(
    private val childProvider: () -> Projection<C>,
    private val relationCondition: (Projection<C>) -> Condition,
    private val orderBy: (Projection<C>) -> List<SortField<*>>,
    private val defaultLimit: Int = 20,
    private val maxLimit: Int = 100,
) : RelationNode {
    init { require(defaultLimit in 1..maxLimit) }

    override fun compile(
        selection: Selection,
        context: ProjectionContext,
        depth: Int,
    ): Field<*> {
        val child = childProvider()
        val compiled = child.compile(selection, context, depth)
        val limit = selection.intArgument("limit", defaultLimit)
        val offset = selection.intArgument("offset", 0)
        require(limit in 1..maxLimit) { "limit must be in 1..$maxLimit" }
        require(offset >= 0) { "offset must not be negative" }
        val sorting = orderBy(child)
        require(sorting.isNotEmpty()) { "Collection needs stable ordering" }

        val query = DSL.select(compiled.fields).from(child.table)
            .where(compiled.condition)
            .and(relationCondition(child))
            .orderBy(sorting).limit(limit).offset(offset)

        return DSL.multiset(query).convertFrom { rows -> rows.map(compiled::wrap) }
    }
}

/** Convert JSONB columns via jOOQ so wrapper getters receive already decoded values. */
fun <T : Any> jsonb(
    field: Field<JSONB?>,
    serializer: KSerializer<T>,
    json: Json,
): Field<T?> = field.convertFrom { raw ->
    raw?.let { json.decodeFromString(serializer, it.data()) }
}

fun String.toCamelCase(): String =
    split('_').mapIndexed { index, part ->
        if (index == 0) part else part.replaceFirstChar { it.uppercase() }
    }.joinToString("")

fun autoMappings(fields: Array<out Field<*>>): Map<String, Field<*>> =
    fields.associateBy { it.name.toCamelCase() }
