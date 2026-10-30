package com.sylus.app.auth

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PkceUtilsTest {

    @Test
    fun generateCodeVerifier_returnsValidNonEmptyString() {
        val verifier = PkceUtils.generateCodeVerifier()
        assertNotNull(verifier)
        assertTrue(verifier.length >= 43)
    }

    @Test
    fun generateCodeChallenge_returnsDeterministicHashForGivenVerifier() {
        val verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        val challenge1 = PkceUtils.generateCodeChallenge(verifier)
        val challenge2 = PkceUtils.generateCodeChallenge(verifier)

        assertEquals(challenge1, challenge2)
        assertTrue(challenge1.isNotEmpty())
    }
}
