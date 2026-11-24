# Multi-Plattform-Releases: belegter Status und Prüfanleitung

## Versionsgebundener Installationspfad (2026-11-24, PR #354)

Der neue [Release-Vertrag](PLATFORM_RELEASES.md) verbindet einen getesteten
`main`-Commit mit einer gemeinsamen SemVer-Version für Windows, Linux,
Android und Firefox. Windows und Linux enthalten die Python-CPU-Engine und
benötigen keine separat installierte Python-Laufzeit. Android bleibt der
HTTPS-Gradio-Client; Firefox bleibt das lokale Diagnose-Add-on.

**Erste native Abnahme tatsächlich erfolgreich:**
[Desktop-Lauf 45481727697](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/45481727697)
prüfte Windows x64 und Linux x86_64 am PR-Testmerge
`f95800660eb36a18e406b99a23ceae37fbec7f5a`, dessen Tree
`fec1b96a8c6bdad8c201a005c84ca417dd275bd0` dem Quell-Head
`4743ad7e926bcd91ffafedbdda001766512315bf` entspricht. Auf beiden Plattformen:
echte Installation, Start außerhalb des Checkouts, Versions-/Quellprüfung,
CPU-Render und Deinstallation mit Erhalt einer fremden Benutzerdatei. Die
vollständigen 230.454 BMP-Bytes stimmen mit dem Quelllauf überein
(SHA-256 `498a2193dac5681033deac1838573094a45e7cd64ff5c3514db35d681c879adb`).

Der
[GoReleaser-Prüflauf 45481727661](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/45481727661)
hat Konfiguration, Wheel und Snapshot geprüft. Seine Veröffentlichungsjobs
sind im PR absichtlich übersprungen; dies ist kein Release-Nachweis.
Der erste Windows-Lauf hatte einen reproduzierten CP1252/UTF-8-Fehler im
CLI-Readback. Der Fix setzt explizite UTF-8-Ausgabe und striktes Decoding;
die ursprünglichen Fehlerlogs und die erfolgreichen Folgeprüfungen bleiben
in der PR-Evidence erhalten.

**Versioniertes Firefox-Paket tatsächlich im Browser ausgeführt:** Das
gestagte XPI `1.2.50` (SHA-256
`99a814b6a8c997a9c8f86f5e766e5a8b74017615a7da20d997c5cda4c1e20a1b`)
bestand im isolierten Nightly-Build `20261123184640` den Toolbar-, Versions-
und JSON-Downloadablauf sowie den Vergleich aller 4.096 WebGL-Pixel.
Runtime-Receipt SHA-256:
`2f3f59705d5f6c35fd9797f1cc26ef20da5fd972c13966133a66045c840be748`.
WebGPU default/fallback waren tatsächlich `unavailable`, beide mit
`acceptedPass: false`. Dieser vor dem Commit gebaute Kandidat ist ein
paketgebundener Browserbeleg, kein veröffentlichter Release und kein
ARE-Treiber-Nachweis. Der archivverifizierte Browser und das XPI blieben
unverändert; die temporäre Erweiterung wurde entfernt.

Die gemeinsame Android-/Firefox-Veröffentlichung wird erst nach einem
erfolgreichen Desktop-Release für denselben Tag zugelassen. Ein CI-Testschlüssel
ist keine dauerhafte Android-Signatur. Ein unsigniertes XPI ist keine
Mozilla-Freigabe. Der tatsächliche Signier- und Veröffentlichungsstatus wird
in den jeweiligen Release-Jobs und deren Readback belegt; fehlende Zugangsdaten
blockieren den betroffenen Signierschritt ausdrücklich.

Die nachfolgenden Einträge sind historische Beobachtungen des früheren
SHA-basierten Gradio-Vorschaupfades. Sie belegen keine heutigen nativen
Installationspakete und keine neue Veröffentlichung.

## Historischer erfolgreicher Release-Readback (2026-10-13)

**GitHub Release tatsächlich veröffentlicht:** [Gradio Android / Linux / Windows / npm für Commit `14e7a3f39dbf06c61c0e9ae33fb4f41b5ed4d990`](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/releases/tag/gradio-android-14e7a3f39dbf06c61c0e9ae33fb4f41b5ed4d990).

Der [erfolgreiche Build-/Release-Lauf 38332775462](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38332775462) hat die echten APK-, Linux-/Windows-ZIP- und npm-tgz-Artefakte gebaut, geprüft, `npm publish` nach GitHub Packages **erfolgreich ausgeführt**, den GitHub-Packages-Registry-Readback bestanden und sechs Assets an den GitHub-Release-Tag gebunden. Der zugrunde liegende CPU-regressions-Lauf [38332519681](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38332519681) war grün. Es gibt weiterhin keinen bestätigten Live-Gradio-Server, Android-Gerätetest oder dauerhaft signierte Update-APK. Die Windows-/Linux-ZIPs benötigen Node.js 20+.

**Chronologie:** Die nachfolgend genannte `ENEEDAUTH`-Fehlermeldung betrifft den älteren ersten Release-Lauf. Sie ist durch den späteren, erfolgreichen Run **überholt**, nicht weiterhin der aktuelle Veröffentlichungsstatus.


**Stand der dokumentierten Bestandsaufnahme:** 2026-10-13, `main`-SHA `db9ba894f29254fc67f4d3c808807f89ab721103`.

Die [CPU-regressions-Push-CI](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38329465850) war erfolgreich. Der automatische [Android-/Node-Release-Lauf](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38329782084) hat **Android-APK, Linux-/Windows-Archive und npm-Tarball real gebaut und geprüft**, scheiterte aber danach an `npm ERR! ENEEDAUTH`. Somit wurden bei dieser Bestandsaufnahme **keine GitHub-Releases** angezeigt; ein npm-Registry-Publish ist ebenfalls nicht nachgewiesen.

## Historischer Live-Readback vor dem erfolgreichen Lauf (2026-10-13)

- Repository ist **public**; GitHub Pages ist nicht aktiviert. Die Projekt-Homepage-Metadaten verweisen auf `https://arelogic.space`, aber eine daraus resultierende SoftwareGPU-Demo wurde nicht nachgewiesen.
- Bei dieser erneuten Prüfung meldete die GitHub-Releases-API **keine Releases/Assets**. Siehe [Releases](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/releases).
- Der beobachtete `main`-Commit `14e7a3f39dbf06c61c0e9ae33fb4f41b5ed4d990` hatte noch eine laufende [CPU-CI](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38332519681). Damit ist die automatische Release-Kette für diesen Stand **nicht als abgeschlossen verifiziert**.
- Die älteren Workflow-Ergebnisse mit `failure` und `skipped` zeigen, dass ein erfolgreicher App-/APK-Build nicht automatisch einen erfolgreichen npm-Publish oder ein veröffentlichtes Release bedeutet.

## Ursache und Nachbesserung

Die Registry-`.npmrc` verwendete literal `\\n` statt echte Zeilenumbrüche, wodurch npm die GitHub-Packages-Anmeldung nicht erkennen konnte. Der Folge-PR korrigiert `printf` für die Registry und Linux-/Windows-Launcher, kontrolliert das Registry-URL-Parsing, prüft die veröffentlichten npm-Metadaten nach und liefert Lizenz/Required Notices mit. **Erfolg erst behaupten, wenn der neue Head vollständig grün und ein GitHub-Release samt npm-Paket durch Readback nachgewiesen ist.**

## Damaliger Gradio-Vorschauvertrag (2026-10-13)

| Asset | Tatsächlicher Typ | Grenzen |
| --- | --- | --- |
| `ARE-SoftwareGPU-Gradio-Android-preview.apk` | Android-WebView-Debug-APK | Nicht dauerhaft updatefähig signiert; kein Gerätetest |
| `ARE-Gradio-Linux.zip` | Shell-Launcher und JavaScript-CLI | Node.js 20+ separat notwendig |
| `ARE-Gradio-Windows.zip` | CMD-Launcher und JavaScript-CLI | Node.js 20+ separat notwendig |
| `*.tgz` | Mit `npm pack` gebautes Node-Paket | Registry-Veröffentlichung getrennt prüfen |
| `*.sha256` | SHA256-Dateihashes | Vor Verwendung verifizieren |

Die Clients laufen **nicht** ohne eigene HTTPS-Gradio-Instanz. Die Gradio-Engine selbst bleibt standardmäßig lokal und authentifiziert.

## Historische Prüfanleitung für den Gradio-Vorschaupfad

1. Den exakten getesteten Commit in der `CPU regressions`-Workflow-Run-Seite verifizieren.
2. Den daran ausgelösten `Android Gradio APK prerelease`-Workflow öffnen. Alle Jobs einschließlich `npm publish` und npm-`view`-Readback müssen grün sein.
3. Auf der [Release-Seite](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/releases) Tag, Ziel-SHA und **alle** herunterladbaren Assets prüfen.
4. SHA256 der Archive lokal kontrollieren; Android-Installation, App-Start und HTTPS-Serververbindung auf einem **echten Gerät** gesondert nachweisen, bevor „Android-kompatibel getestet“ behauptet wird.
5. Für reguläre Update-APKs erst persistenten, geheim gehaltenen Release-Signing-Key und Emulator-/Geräte-Abnahme ergänzen.

GitHub-Packages benötigt passende Berechtigungen/Package-Zugriffsrichtlinien; selbst mit korrigierter npmrc kann externe Berechtigung eine Veröffentlichung blockieren. Es gibt keine automatische Veröffentlichung auf `registry.npmjs.org`.
