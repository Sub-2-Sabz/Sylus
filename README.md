# Sylus - Mobile App (Milestone 1)

Sylus is an Android application built with Kotlin, Jetpack Compose, Material 3, and Gradle Version Catalog.

---

## Features (Milestone 1)

- **Gradle Build System:** Kotlin DSL build scripts with Gradle Version Catalog (`gradle/libs.versions.toml`).
- **Theme Engine:** Supports Light, Dark, OLED (pure black), and Dynamic Color (Material You) theme modes alongside custom accent color selection. Settings screen included.
- **Lichess OAuth2 PKCE Login:** Authenticate securely with Lichess via OAuth2 PKCE flow.
- **Home Screen:** Simple home screen displaying the logged-in username or login controls.
- **CI/CD Pipeline:** GitHub Actions workflow (`.github/workflows/build.yml`) that builds the debug APK and uploads it as an artifact.

---

## Building and Running

### Requirements
- JDK 21
- Android SDK (Target SDK 35)
- Gradle 8.8 (using Gradle Wrapper)

### Build Debug APK
```bash
./gradlew assembleDebug
```

The compiled APK will be located at `app/build/outputs/apk/debug/app-debug.apk`.

### Run Unit Tests
```bash
./gradlew test
```

---

## License

This project is licensed under the [MIT License](LICENSE).
