# ARE SoftwareGPU Engine — Integrationsstatus

Quelle: vom Projektinhaber am 2026-10-08 hochgeladenes neues TAR-Archiv (SoftwareGPU 1.2.0).
Das Archiv enthaelt Python-Software-Rasterisierung, Compute-Kernels, MSAA/FXAA, Demo-D3D11-API, Android/Netzwerk-Clients, Benchmarks und MMORPG-Demos.

## Verifizierter lokaler Ausgangszustand
- 22 von 22 unittest-Tests erfolgreich in isolierter lokaler Python-Umgebung.
- Dies beweist **nicht** native DirectX-11/CUDA- oder Android-Kompatibilitaet.
- Matrix-Kernels verwenden NumPy/CPU; gemeldete Benchmarkwerte muessen auf reproduzierbaren Systemen gegen CPU-Baselines validiert werden.
- Netzwerk-HTTP-Service hat offenen CORS-Header und keine Authentisierung; NICHT oeffentlich exponieren.
- MMORPG-Code ist kein Aurion-Gameplay-Authority-Ersatz.

## Sicherheits- und Architekturvertrag
- CPU-only; keine Hardware-GPU voraussetzen.
- Kein Eintritt in die kanonische Aurion-Tick-/Persistenz-/Authority-Grenze.
- Spätere Anbindung nur als externer read-only/offline Worker mit CPU-/RAM-/Zeitlimits und Hash-/Receipt-Nachweis.
- Ergebnisse nur als abgeleitete Evidence/Renderartefakte, niemals als Gameplay-Wahrheit.
- Quellarchiv vor Aktivierung auf externe Endpunkte/Secrets pruefen.
- Alte generated BMP/PPM/egg-info/__pycache__ Artefakte nicht in den Quellbaum importieren.

## Offene Integrationsschritte
1. Saemtliche Python-Quellmodule und Client-Beispiele aus TAR als reviewbaren Git-Baum importieren.
2. Packaging, Syntax, CLI und bestehende 22 Unit-Tests unter Linux reproduzieren.
3. Negative Tests fuer Protokoll-Payload-/Groessenlimits, Authentisierung, Synchronisationsbarrieren und Schwarm-Tempo.
4. Cross-Platform-CI und Benchmark-Baselines mit dokumentierten CPU-/Speicherangaben.
5. Erst danach Read-only Aurion-Adapter und Vergleichstests.
6. Memory.md: genau ein kurzer Eintrag mit Aenderung, Erkenntnis und Evidence vor Merge.

Dieser Branch ist bewusst ein **Projekt- und Evidence-Bootstrap**, noch kein vollstaendiger Import und keine Produktionsfreigabe.
