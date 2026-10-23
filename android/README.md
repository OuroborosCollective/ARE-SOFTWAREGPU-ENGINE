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

## Gleichzeitige Node- und Desktop-Veröffentlichung

Der SHA-gebundene GitHub-Prerelease bündelt Android-Debug-APK, Linux/Windows-
Node-Launcher-ZIPs, den getesteten npm-Tarball und SHA256-Listen. Linux und
Windows benötigen Node.js >=20; es handelt sich nicht um native Standalone-
Binaries. Der Node-Client überprüft die echte HTTPS-`/config`-Route und meldet
401/403 ehrlich als geschützte Instanz. Die ZIP-Clients sind ohne Gradio-Server
nur Verbindungstests/Launcher, keine lokale GPU-Engine.

Ein erfolgreicher `main`-Lauf soll zusätzlich eine commitgebundene Version nach
GitHub Packages (`@ouroboroscollective/softwaregpu-gradio-client`) publizieren.
Das erfordert gültige Organisationsrechte für `GITHUB_TOKEN` mit
`packages: write`; falls das fehlschlägt, darf kein kompletter Release
behauptet werden. Es erfolgt kein automatischer Publish zur öffentlichen
`registry.npmjs.org` ohne gesonderte npm-Publisher-Autorisierung.

## Geführter Teststart (neue UI im Forschungs-PR)

Die App zeigt zuerst einen verständlichen Verbindungsassistenten statt einer leeren Gradio-Maske. Der Benutzer benötigt **einmal** eine bereits bereitgestellte, authentifizierte HTTPS-Adresse des ARE-Testservers; die APK ist weiterhin ein WebView-Client und kann ohne diesen Rechner keine Renderjobs ausführen. Kein öffentliches Demo-Ziel, kein eingebettetes Passwort und kein unsicherer HTTP-Fallback.

Nach Anmeldung zeigt der überarbeitete serverseitige CPU-Testbereich vier sofort wählbare Vorlagen: **Schnelltest (64 Pixel)**, **Standard (128 Pixel)**, **Detailtest (256 Pixel)** und **Referenzvergleich (Bands)**. Die Auswahl setzt Seed, Auflösung und Renderer automatisch. Der Button **Test starten** verwendet weiter den echten isolierten Worker mit drei Replays, Bild-SHA-256-Readback und unverändertem Budget. Technische Receipts stehen einklappbar unter dem gerenderten Bild. Diese Oberfläche ist nur verfügbar, wenn sowohl App **als auch Server** den neuen Code verwenden.

**Prüfung:** `python -m unittest software_gpu.tests.test_gradio_arena -v`; Android-Build `gradle -p android :app:assembleDebug` benötigt JDK 17/SDK 35. Keine Aussage über erfolgreiche Geräteinstallation oder neuen APK-Release ohne passenden Workflow- und Geräte-Readback.

**Geplante Serveradresse:** `https://gpu.arelorian.de` (noch nicht als online bestätigt). Der separierte 3-vCPU-Worker und sein projektgenauer Docker-Cleanup sind in [der VPS-Worker-Anleitung](../ops/softwaregpu-worker/README.md) spezifiziert. Bis DNS, SSL-Zertifikat, freigegebene Host-Installation und echter Tablet-Login durchgängig funktionieren, den Platzhalter in der APK nicht durch eine erfundene IP ersetzen.
