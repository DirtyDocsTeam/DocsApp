package ru.dirtydocs.api.users

import kotlinx.serialization.json.Json
import org.jooq.impl.DSL
import ru.dirtydocs.api.users.tokens.Token
import ru.dirtydocs.api.users.tokens.access.TokenAccessRights
import ru.novari.data.ManyRelation
import ru.novari.data.Projection
import ru.novari.data.columnNodes
import ru.novari.data.jsonb
import ru.novari.spectra.generated.jooq.tables.references.API_TOKENS
import ru.novari.spectra.generated.jooq.tables.references.USERS
import kotlin.collections.plus

object UserProjections {
    private val json = Json {
        ignoreUnknownKeys = true
        decodeEnumsCaseInsensitive = true
    }
    val TOKEN: Projection<Token> = Projection(
        table = API_TOKENS,
        id = API_TOKENS.ID,
        nodes = columnNodes(
            mapOf(
                "id" to API_TOKENS.ID,
                "createdAt" to API_TOKENS.CREATED_AT,
                "expiresAt" to API_TOKENS.EXPIRES_AT,
                "access" to jsonb(API_TOKENS.ACCESS, TokenAccessRights.serializer(), json)
            )
        ),
        required = setOf("id"),
        factory = ::Token,
        access = { context ->
            context.viewerId?.let { viewerId ->
                API_TOKENS.USER_ID.eq(viewerId)
            } ?: DSL.falseCondition()
        }
    )

    val USER: Projection<User> = Projection(
        table = USERS,
        id = USERS.ID,
        nodes = columnNodes(
            mapOf(
                "id" to USERS.ID,
                "email" to USERS.EMAIL,
                "roles" to USERS.SYSTEM_ROLES,
                "createdAt" to USERS.CREATED_AT,
                "updatedAt" to USERS.UPDATED_AT,
                "tokens" to USERS.TOKENS,
                "lastTokenChangeAt" to USERS.LAST_TOKEN_CHANGE_AT,
            )
        ) + mapOf(
            "apiTokens" to ManyRelation(
                childProvider = { TOKEN },
                relationCondition = { API_TOKENS.USER_ID.eq(USERS.ID) },
                orderBy = {
                    listOf(API_TOKENS.CREATED_AT.desc(), API_TOKENS.ID.desc())
                },
                defaultLimit = 10,
                maxLimit = 100
            )
        ),
        required = setOf("id"),
        factory = ::User,
        access = { context ->
            context.viewerId?.let { viewerId ->
                USERS.ID.eq(viewerId)
            } ?: DSL.falseCondition()
        }
    )
}
