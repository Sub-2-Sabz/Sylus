package com.sylus.app.ui.theme

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class ThemeRepository(context: Context) {

    private val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private val _themeState = MutableStateFlow(loadThemeState())
    val themeState: StateFlow<ThemeState> = _themeState.asStateFlow()

    private fun loadThemeState(): ThemeState {
        val modeName = prefs.getString(KEY_THEME_MODE, ThemeMode.DARK.name) ?: ThemeMode.DARK.name
        val themeMode = try {
            ThemeMode.valueOf(modeName)
        } catch (e: Exception) {
            ThemeMode.DARK
        }
        val accentArgb = prefs.getInt(KEY_ACCENT_COLOR, Color(0xFF6200EE).toArgb())
        return ThemeState(
            themeMode = themeMode,
            customAccentColor = Color(accentArgb)
        )
    }

    fun setThemeMode(mode: ThemeMode) {
        prefs.edit().putString(KEY_THEME_MODE, mode.name).apply()
        _themeState.value = _themeState.value.copy(themeMode = mode)
    }

    fun setCustomAccentColor(color: Color) {
        prefs.edit().putInt(KEY_ACCENT_COLOR, color.toArgb()).apply()
        _themeState.value = _themeState.value.copy(customAccentColor = color)
    }

    companion object {
        private const val PREFS_NAME = "sylus_theme_prefs"
        private const val KEY_THEME_MODE = "theme_mode"
        private const val KEY_ACCENT_COLOR = "accent_color"
    }
}
