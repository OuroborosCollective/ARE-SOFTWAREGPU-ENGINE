# Android Gradio Companion (Preview)

Die APK ist ein Android-WebView-Client für eine bestehende HTTPS-Gradio-Instanz.
Sie enthält **keinen CPU-/C++-Renderer**, keine eingebetteten Zugangsdaten und
keinen Backend-Dienst. Sie akzeptiert nur HTTPS und deaktiviert lokale Datei-/
Content-Zugriffe. Für den Livebetrieb eine separat geprüfte öffentliche
HTTPS-Adresse hinter Authentifizierung und Rate Limits bereitstellen.

Build: `gradle -p android :app:assembleDebug` (JDK 17 + Android SDK 35).
Die automatisch erzeugte **Debug-APK** ist nur eine installierbare Vorschau:
Die Runner-Debug-Signatur ist nicht dauerhaft stabil. Vor einer regulären
updatefähigen APK einen sicheren, persistenten Signing-Key als GitHub Secret
hinterlegen und den Release-Build auf `assembleRelease` mit konsistenter
Signatur und Android-Geräte-E2E umstellen. Keine Secrets in Source oder Logs.

Release-Workflow: Nach erfolgreichem `CPU regressions`-Workflow auf
`main` baut er die APK aus genau dessen Head-SHA, prüft APK/AAPT und SHA256
und erstellt ein SHA-gebundenes GitHub Prerelease. Fehlgeschlagene CI und PRs
lösen **keine** Veröffentlichung aus.
