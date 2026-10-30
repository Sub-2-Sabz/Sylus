package com.sylus.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.lifecycle.lifecycleScope
import com.sylus.app.auth.LichessAuthRepository
import com.sylus.app.ui.home.HomeScreen
import com.sylus.app.ui.settings.SettingsScreen
import com.sylus.app.ui.theme.SylusTheme
import com.sylus.app.ui.theme.ThemeRepository
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private lateinit var themeRepository: ThemeRepository
    private lateinit var authRepository: LichessAuthRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        themeRepository = ThemeRepository(applicationContext)
        authRepository = LichessAuthRepository(applicationContext)

        handleIntent(intent)

        setContent {
            val themeState by themeRepository.themeState.collectAsState()
            val authState by authRepository.authState.collectAsState()

            var currentScreen by remember { mutableStateOf(Screen.HOME) }

            LaunchedEffect(Unit) {
                authRepository.checkAuthState()
            }

            SylusTheme(themeState = themeState) {
                when (currentScreen) {
                    Screen.HOME -> {
                        HomeScreen(
                            authState = authState,
                            onLoginClicked = {
                                val url = authRepository.buildAuthorizationUrl()
                                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                                startActivity(intent)
                            },
                            onLogoutClicked = {
                                authRepository.logout()
                            },
                            onSettingsClicked = {
                                currentScreen = Screen.SETTINGS
                            }
                        )
                    }
                    Screen.SETTINGS -> {
                        SettingsScreen(
                            themeState = themeState,
                            onThemeModeSelected = { mode ->
                                themeRepository.setThemeMode(mode)
                            },
                            onAccentColorSelected = { color ->
                                themeRepository.setCustomAccentColor(color)
                            },
                            onBackClicked = {
                                currentScreen = Screen.HOME
                            }
                        )
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        val data: Uri? = intent?.data
        if (data != null && data.scheme == "sylus" && data.host == "oauth") {
            val code = data.getQueryParameter("code")
            if (!code.isNullOrEmpty()) {
                lifecycleScope.launch {
                    authRepository.handleAuthCallback(code)
                }
            }
        }
    }

    private enum class Screen {
        HOME,
        SETTINGS
    }
}
