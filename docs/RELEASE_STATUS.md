# Multi-Plattform-Releases: belegter Status und Prüfanleitung

**Stand der dokumentierten Bestandsaufnahme:** 2026-10-13, `main`-SHA `db9ba894f29254fc67f4d3c808807f89ab721103`.

Die [CPU-regressions-Push-CI](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38329465850) war erfolgreich. Der automatische [Android-/Node-Release-Lauf](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38329782084) hat **Android-APK, Linux-/Windows-Archive und npm-Tarball real gebaut und geprüft**, scheiterte aber danach an `npm ERR! ENEEDAUTH`. Somit wurden bei dieser Bestandsaufnahme **keine GitHub-Releases** angezeigt; ein npm-Registry-Publish ist ebenfalls nicht nachgewiesen.

## Ursache und Nachbesserung

Die Registry-`.npmrc` verwendete literal `\\n` statt echte Zeilenumbrüche, wodurch npm die GitHub-Packages-Anmeldung nicht erkennen konnte. Der Folge-PR korrigiert `printf` für die Registry und Linux-/Windows-Launcher, kontrolliert das Registry-URL-Parsing, prüft die veröffentlichten npm-Metadaten nach und liefert Lizenz/Required Notices mit. **Erfolg erst behaupten, wenn der neue Head vollständig grün und ein GitHub-Release samt npm-Paket durch Readback nachgewiesen ist.**

## Was GitHub künftig pro erfolgreicher `main`-CI erzeugen soll

| Asset | Tatsächlicher Typ | Grenzen |
| --- | --- | --- |
| `ARE-SoftwareGPU-Gradio-Android-preview.apk` | Android-WebView-Debug-APK | Nicht dauerhaft updatefähig signiert; kein Gerätetest |
| `ARE-Gradio-Linux.zip` | Shell-Launcher und JavaScript-CLI | Node.js 20+ separat notwendig |
| `ARE-Gradio-Windows.zip` | CMD-Launcher und JavaScript-CLI | Node.js 20+ separat notwendig |
| `*.tgz` | Mit `npm pack` gebautes Node-Paket | Registry-Veröffentlichung getrennt prüfen |
| `*.sha256` | SHA256-Dateihashes | Vor Verwendung verifizieren |

Die Clients laufen **nicht** ohne eigene HTTPS-Gradio-Instanz. Die Gradio-Engine selbst bleibt standardmäßig lokal und authentifiziert.

## Release-Abnahme

1. Den exakten getesteten Commit in der `CPU regressions`-Workflow-Run-Seite verifizieren.
2. Den daran ausgelösten `Android Gradio APK prerelease`-Workflow öffnen. Alle Jobs einschließlich `npm publish` und npm-`view`-Readback müssen grün sein.
3. Auf der [Release-Seite](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/releases) Tag, Ziel-SHA und **alle** herunterladbaren Assets prüfen.
4. SHA256 der Archive lokal kontrollieren; Android-Installation, App-Start und HTTPS-Serververbindung auf einem **echten Gerät** gesondert nachweisen, bevor „Android-kompatibel getestet“ behauptet wird.
5. Für reguläre Update-APKs erst persistenten, geheim gehaltenen Release-Signing-Key und Emulator-/Geräte-Abnahme ergänzen.

GitHub-Packages benötigt passende Berechtigungen/Package-Zugriffsrichtlinien; selbst mit korrigierter npmrc kann externe Berechtigung eine Veröffentlichung blockieren. Es gibt keine automatische Veröffentlichung auf `registry.npmjs.org`.
