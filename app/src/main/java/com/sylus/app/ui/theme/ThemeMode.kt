package com.sylus.app.ui.theme

import androidx.compose.ui.graphics.Color

enum class ThemeMode {
    LIGHT,
    DARK,
    OLED,
    DYNAMIC
}

data class ThemeState(
    val themeMode: ThemeMode = ThemeMode.DARK,
    val customAccentColor: Color = Color(0xFF6200EE)
)

val AccentColors = listOf(
    Color(0xFF6200EE), // Purple / Default
    Color(0xFF03DAC6), // Teal
    Color(0xFFE91E63), // Pink
    Color(0xFFFF9800), // Orange
    Color(0xFF4CAF50), // Green
    Color(0xFF2196F3), // Blue
    Color(0xFF9C27B0)  // Deep Purple
)
