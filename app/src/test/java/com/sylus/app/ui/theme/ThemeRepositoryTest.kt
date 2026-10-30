package com.sylus.app.ui.theme

import android.content.Context
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import com.sylus.app.ui.theme.ThemeMode
import com.sylus.app.ui.theme.ThemeRepository
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.mockito.Mockito.`when`
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify

class ThemeRepositoryTest {

    private lateinit var context: Context
    private lateinit var sharedPreferences: android.content.SharedPreferences
    private lateinit var editor: android.content.SharedPreferences.Editor
    private lateinit var themeRepository: ThemeRepository

    @Before
    fun setUp() {
        context = mock(Context::class.java)
        sharedPreferences = mock(android.content.SharedPreferences::class.java)
        editor = mock(android.content.SharedPreferences.Editor::class.java)

        `when`(context.getSharedPreferences("sylus_theme_prefs", Context.MODE_PRIVATE)).thenReturn(sharedPreferences)
        `when`(sharedPreferences.edit()).thenReturn(editor)
        `when`(editor.putString(any(), any())).thenReturn(editor)
        `when`(editor.putInt(any(), anyInt())).thenReturn(editor)
        `when`(sharedPreferences.getString("theme_mode", ThemeMode.DARK.name)).thenReturn(ThemeMode.DARK.name)
        `when`(sharedPreferences.getInt("accent_color", Color(0xFF6200EE).toArgb())).thenReturn(Color(0xFF6200EE).toArgb())

        themeRepository = ThemeRepository(context)
    }

    private fun <T> any(): T = org.mockito.Mockito.any()
    private fun anyInt(): Int = org.mockito.Mockito.anyInt()

    @Test
    fun defaultThemeState_isDarkAndPurple() {
        val state = themeRepository.themeState.value
        assertEquals(ThemeMode.DARK, state.themeMode)
    }

    @Test
    fun setThemeMode_updatesStateAndPersists() {
        themeRepository.setThemeMode(ThemeMode.OLED)
        assertEquals(ThemeMode.OLED, themeRepository.themeState.value.themeMode)
        verify(editor).putString("theme_mode", ThemeMode.OLED.name)
    }

    @Test
    fun setCustomAccentColor_updatesStateAndPersists() {
        val newColor = Color(0xFFE91E63)
        themeRepository.setCustomAccentColor(newColor)
        assertEquals(newColor, themeRepository.themeState.value.customAccentColor)
        verify(editor).putInt("accent_color", newColor.toArgb())
    }
}
