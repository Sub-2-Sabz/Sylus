package com.sylus.app.auth

import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

data class LichessUser(
    val id: String,
    val username: String,
    val rating: Int? = null
)

sealed class AuthState {
    data object Unauthenticated : AuthState()
    data object Loading : AuthState()
    data class Authenticated(val user: LichessUser) : AuthState()
    data class Error(val message: String) : AuthState()
}

class LichessAuthRepository(
    context: Context,
    private val clientId: String = CLIENT_ID,
    private val redirectUri: String = REDIRECT_URI
) {
    private val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private val _authState = MutableStateFlow<AuthState>(AuthState.Unauthenticated)
    val authState: StateFlow<AuthState> = _authState.asStateFlow()

    private var currentCodeVerifier: String?
        get() = prefs.getString(KEY_CODE_VERIFIER, null)
        set(value) {
            prefs.edit().putString(KEY_CODE_VERIFIER, value).apply()
        }

    var accessToken: String?
        get() = prefs.getString(KEY_ACCESS_TOKEN, null)
        private set(value) {
            prefs.edit().putString(KEY_ACCESS_TOKEN, value).apply()
        }

    init {
        // Restore session if access token exists
        accessToken?.let { token ->
            _authState.value = AuthState.Loading
            // Profile fetch will be performed via checkAuthState()
        }
    }

    suspend fun checkAuthState() {
        val token = accessToken
        if (token == null) {
            _authState.value = AuthState.Unauthenticated
            return
        }

        _authState.value = AuthState.Loading
        try {
            val user = fetchProfile(token)
            if (user != null) {
                _authState.value = AuthState.Authenticated(user)
            } else {
                logout()
            }
        } catch (e: Exception) {
            _authState.value = AuthState.Error("Failed to fetch user profile: ${e.localizedMessage}")
        }
    }

    fun buildAuthorizationUrl(): String {
        val verifier = PkceUtils.generateCodeVerifier()
        currentCodeVerifier = verifier
        val challenge = PkceUtils.generateCodeChallenge(verifier)

        return Uri.parse(LICHESS_AUTHORIZE_URL).buildUpon()
            .appendQueryParameter("response_type", "code")
            .appendQueryParameter("client_id", clientId)
            .appendQueryParameter("redirect_uri", redirectUri)
            .appendQueryParameter("code_challenge_method", "S256")
            .appendQueryParameter("code_challenge", challenge)
            .build()
            .toString()
    }

    suspend fun handleAuthCallback(code: String): Boolean = withContext(Dispatchers.IO) {
        val verifier = currentCodeVerifier ?: return@withContext false
        _authState.value = AuthState.Loading

        try {
            val url = URL(LICHESS_TOKEN_URL)
            val connection = url.openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
            connection.doOutput = true

            val postData = StringBuilder()
                .append("grant_type=").append(URLEncoder.encode("authorization_code", "UTF-8"))
                .append("&code=").append(URLEncoder.encode(code, "UTF-8"))
                .append("&code_verifier=").append(URLEncoder.encode(verifier, "UTF-8"))
                .append("&client_id=").append(URLEncoder.encode(clientId, "UTF-8"))
                .append("&redirect_uri=").append(URLEncoder.encode(redirectUri, "UTF-8"))
                .toString()

            OutputStreamWriter(connection.outputStream).use { writer ->
                writer.write(postData)
                writer.flush()
            }

            if (connection.responseCode == HttpURLConnection.HTTP_OK) {
                val response = connection.inputStream.bufferedReader().use(BufferedReader::readText)
                val json = JSONObject(response)
                val token = json.getString("access_token")
                accessToken = token

                val user = fetchProfile(token)
                if (user != null) {
                    _authState.value = AuthState.Authenticated(user)
                    true
                } else {
                    _authState.value = AuthState.Error("Failed to fetch user profile after token exchange")
                    false
                }
            } else {
                val errorStream = connection.errorStream?.bufferedReader()?.use(BufferedReader::readText) ?: ""
                _authState.value = AuthState.Error("Token exchange failed (${connection.responseCode}): $errorStream")
                false
            }
        } catch (e: Exception) {
            _authState.value = AuthState.Error("OAuth authentication error: ${e.localizedMessage}")
            false
        }
    }

    private suspend fun fetchProfile(token: String): LichessUser? = withContext(Dispatchers.IO) {
        try {
            val url = URL(LICHESS_ACCOUNT_URL)
            val connection = url.openConnection() as HttpURLConnection
            connection.requestMethod = "GET"
            connection.setRequestProperty("Authorization", "Bearer $token")

            if (connection.responseCode == HttpURLConnection.HTTP_OK) {
                val response = connection.inputStream.bufferedReader().use(BufferedReader::readText)
                val json = JSONObject(response)
                val id = json.getString("id")
                val username = json.getString("username")
                LichessUser(id = id, username = username)
            } else {
                null
            }
        } catch (e: Exception) {
            null
        }
    }

    fun logout() {
        accessToken = null
        currentCodeVerifier = null
        _authState.value = AuthState.Unauthenticated
    }

    companion object {
        const val CLIENT_ID = "sylus-mobile-app"
        const val REDIRECT_URI = "sylus://oauth/callback"

        private const val LICHESS_AUTHORIZE_URL = "https://lichess.org/oauth"
        private const val LICHESS_TOKEN_URL = "https://lichess.org/api/token"
        private const val LICHESS_ACCOUNT_URL = "https://lichess.org/api/account"

        private const val PREFS_NAME = "sylus_auth_prefs"
        private const val KEY_ACCESS_TOKEN = "access_token"
        private const val KEY_CODE_VERIFIER = "code_verifier"
    }
}
