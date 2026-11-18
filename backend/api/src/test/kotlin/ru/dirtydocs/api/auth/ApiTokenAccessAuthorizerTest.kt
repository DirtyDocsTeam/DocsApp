package ru.dirtydocs.api.auth

import io.quarkus.security.identity.SecurityIdentity
import jakarta.ws.rs.ForbiddenException
import org.junit.jupiter.api.Assertions.assertDoesNotThrow
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import org.mockito.Mockito.mock
import org.mockito.Mockito.`when`
import ru.dirtydocs.api.users.tokens.access.AccessPermissions
import ru.dirtydocs.api.users.tokens.access.TokenAccessRights

class ApiTokenAccessAuthorizerTest {
    @Test
    fun allowsOidcAndAnonymousIdentities() {
        val identity = mock(SecurityIdentity::class.java)
        val authorizer = ApiTokenAccessAuthorizer(identity)

        assertDoesNotThrow { authorizer.requireRead { it.themes } }
    }

    @Test
    fun rejectsApiTokensWithoutTheRequestedScope() {
        val identity = mock(SecurityIdentity::class.java)
        `when`(identity.getAttribute<TokenAccessRights>(ACCESS_ATTRIBUTE)).thenReturn(TokenAccessRights())
        val authorizer = ApiTokenAccessAuthorizer(identity)

        assertThrows(ForbiddenException::class.java) { authorizer.requireRead { it.themes } }
    }

    @Test
    fun allowsApiTokensWithTheRequestedScope() {
        val identity = mock(SecurityIdentity::class.java)
        val access = TokenAccessRights(themes = AccessPermissions(read = true))
        `when`(identity.getAttribute<TokenAccessRights>(ACCESS_ATTRIBUTE)).thenReturn(access)
        val authorizer = ApiTokenAccessAuthorizer(identity)

        assertDoesNotThrow { authorizer.requireRead { it.themes } }
    }

    @Test
    fun appliesTheJobsScopeIndependently() {
        val identity = mock(SecurityIdentity::class.java)
        val access = TokenAccessRights(jobs = AccessPermissions(read = true))
        `when`(identity.getAttribute<TokenAccessRights>(ACCESS_ATTRIBUTE)).thenReturn(access)
        val authorizer = ApiTokenAccessAuthorizer(identity)

        assertDoesNotThrow { authorizer.requireRead { it.jobs } }
        assertThrows(ForbiddenException::class.java) { authorizer.requireRead { it.themes } }
    }
}
