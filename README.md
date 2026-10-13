# ARE SoftwareGPU Engine

> **CPU-first Software-Rasterisierung, reproduzierbare Grafiktests und experimentelle Compute-Kernels – ohne dedizierte GPU.**
>
> **English subtitle:** A CPU-only software renderer and graphics-compute research engine with tiled rasterization, optional LLVM JIT and reproducible benchmarks.

**Entwickelt von OuroborosCollective · SoftwareGPU 1.2.0 · Source-available, nichtkommerziell**

[![CPU regressions](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/workflows/cpu-regressions.yml/badge.svg)](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/workflows/cpu-regressions.yml) [![Android/Node Preview](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/workflows/android-gradio-apk-release.yml/badge.svg)](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/workflows/android-gradio-apk-release.yml)

[GitHub-Releases (Verfügbarkeit prüfen)](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/releases) · [Visualisierung und Belege](docs/SHOWCASE.md) · [Release-Status](docs/RELEASE_STATUS.md) · [Erste Schritte](docs/QUICKSTART.md) · [Architektur](software_gpu/docs/ARCHITECTURE.md) · [Benchmarks & Evidence](docs/RENDER_OPTIMIZATION_EVIDENCE.md) · [Lizenz](LICENSE.md) · [Namensnennung](NOTICE) · [Kommerzielle Nutzung](docs/LICENSING.md)

![ARE SoftwareGPU: echte CPU-gerenderte Originalmodell-Referenzstichprobe](evidence/native-pbr-20261013/original-arena-smoke.png)

*Original-Arena: archivierte echte CPU-Renderstichprobe, kein Live-Video, keine GPU-Parität und kein 60-FPS-Nachweis. [Bild- und Benchmark-Evidence](docs/native-pbr-arena-report-20261013.md).*

## Try it / Schnell ausprobieren

**English:** ARE SoftwareGPU is a source-available, CPU-only graphics research engine. It includes deterministic tile rasterization, optional LLVM JIT, a bounded native C++17 model/PBR research path and reproducible frame/depth evidence. It is **not** a CUDA, Vulkan, DirectX or hardware-GPU replacement. See the [English/German project overview](docs/PROJECT_OVERVIEW.md) and [real render showcase](docs/SHOWCASE.md).

**Für Neugierige:** [Echte Renderstichprobe](docs/SHOWCASE.md) · [Originalmodell-/PBR-Messbericht](docs/native-pbr-arena-report-20261013.md) · [Python-Schnellstart](docs/QUICKSTART.md) · [Releases](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/releases) · [Probleme und Ideen melden](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/issues) · [Projekt vorstellen / Share this project](docs/SHARE_THE_PROJECT.md).

**Release-Hinweis:** Die GitHub-Release-Seite kann leer sein, obwohl der Quellcode und CI bereits vorhanden sind. Android/Linux/Windows/npm-Clients sind **Remote-Gradio-Clients**, keine installierten nativen Renderer. Ein erfolgreiches Release ist erst mit realen Assets und Registry-Readback belegt. [Aktueller Release-Status](docs/RELEASE_STATUS.md).

## Was ist das?

ARE SoftwareGPU Engine ist ein eigenständiges **CPU-basiertes Grafik- und Compute-Forschungsprojekt**. Es rendert Dreiecke in einen Software-Framebuffer, berechnet Tiefen- und Deckungsmasken, verarbeitet ausgewählte Bildfilter und führt deterministische Vergleichstests aus – auch auf Systemen ohne dedizierte Grafikkarte.

Das Projekt simuliert ausgewählte GPU-nahe Konzepte in Software. **Es ist kein GPU-Gerätetreiber und kein kompatibler Ersatz für DirectX 11, CUDA, Vulkan oder das Training großer Sprachmodelle.** Die vorhandenen Direct3D-/CUDA-artigen Schnittstellen sind experimentelle Python-Adapter. Ein optionaler C++17-Raster- und Modellpfad sowie ein lokaler Gradio-Renderclient sind getrennte Implementierungen und keine Hardware-GPU.

## Funktionen und Nachweisstand

| Bereich | Implementierung | Nachweisgrenze |
| --- | --- | --- |
| Rendering | Software-Framebuffer, Depth-Test, Triangle-Binning und Tile-Rasterisierung | CPU-Bildvergleich auf Linux/Windows |
| Beschleunigung | NumPy-Tiles sowie optionaler Numba/LLVM-JIT für Coverage und Tiefentest | Keine garantierte SIMD-ISA oder GPU-Beschleunigung |
| Kantenglättung | 4× MSAA-Resolve und FXAA | Testbilder/Regression, kein DirectX-Konformitätstest |
| Bildbearbeitung | HDR/Bloom, Tone-Mapping und Filter-Demos | Experimentelle Pipeline |
| Compute | NumPy-Matrixoperationen, Generator-SIMT und Schwarm-Demos | Kein CUDA-Treiber, keine PyTorch-GPU-Anbindung |
| Schnittstellen | HTTP/TCP-Prototyp und Beispielclients verschiedener Sprachen | **Nicht für öffentliche Netze freigegeben** |
| Native C++17-Pipeline | Optionaler CPU-Rasterizer, perspektivisches GLB-Subset (AREMDL03), Metallic-Roughness/PBR | Byte-Paritäts- und Originalmodell-Evidence; kein Vulkan-/GPU-Backend, kein allgemein vollständiger glTF-Importer |
| Gradio | Passwortgeschützte lokale Vorschau, echte isolierte CPU-Jobs/Receipts | Loopback-HTTP-Livetest in CI, kein öffentlich gehosteter Server bestätigt |
| Android/Node-Clients | Debug-APK, Linux-/Windows-Node-Launcher und npm-Tarball im Release-Workflow | Kein Android-Gerätetest und kein eingebetteter Renderer; Veröffentlichung nur nach Registry-/Release-Readback |
| Plattformen | GitHub-CI für Linux und Windows, Python 3.11/3.12 | Android-WebView-/Desktop-Clients gesondert und ohne Gerätelaufzeitnachweis |

### Gemessene Verbesserung

In drei festen CPU-CI-Fixtures wurden die neuen Tiles gegenüber dem historischen Band-Renderer **1,51–1,57×** schneller gemessen, mit optionalem JIT **1,65–1,73×** (separate Runner-Konfigurationen). Die Vergleichsbilder waren in diesen Läufen farbgleich; es gab keine Tiefenabweichung. Diese Zahlen sind **keine** generelle Leistungszusage. [Messaufbau und Grenzen](docs/RENDER_OPTIMIZATION_EVIDENCE.md).

## Schnellstart

Voraussetzung: Python 3.11 oder 3.12 und ein CPU-System.

```bash
python -m pip install -e .
software-gpu --help
software-gpu --info
python -m unittest discover -s software_gpu/tests -v
```

Optionaler CPU-LLVM-Kern und Benchmark:

```bash
python -m pip install -e ".[jit]"
python -m software_gpu.benchmarks.compare_tile_backends --workers 2 --repeats 3 --jit
```

Renderausgaben lassen sich mit `ARE_SOFTWAREGPU_OUTPUT_DIR` in ein eigenes Verzeichnis schreiben. Der experimentelle `--server` ist auf Loopback beschränkt und benötigt einen expliziten Bearer-Token; eine öffentliche TLS-/Mehrmandantenfreigabe ist **nicht** nachgewiesen. [Details](docs/SECURITY_AND_LIMITS.md).

## Projektstruktur

```text
software_gpu/core/          CPU-Gerätemodell, Speicher, Output und VPS-Governor
software_gpu/compute/       Generator-SIMT und NumPy-Compute
software_gpu/graphics/      Renderer, Framebuffer, Tile/LLVM und Postprocessing
software_gpu/benchmarks/    Reale CPU-Benchmarks und Vergleichs-Fixtures
software_gpu/network/       Experimentelle HTTP/TCP-Protokolle
software_gpu/clients/       Sprachübergreifende Prototypen
software_gpu/mobile/        Experimentelle Android-/OpenGL-ES-Adapter
software_gpu/integrations/  Blender-, Image- und MMORPG-Beispiele
software_gpu/tests/         Unit- und Regressionstests
native/symbolic/            C++17-Modell-/PBR- und Workrooms-Forschung
reference_arena/            Three.js-Visualreferenz (GLBs lokal nach Manifest)
plugins/gradio_arena/       Optionales privates Gradio-Frontend
clients/node/               Node-CLI zur HTTPS-Gradio-Instanzprüfung
android/                    Android-WebView-Begleitapp (Debug-Build)
.github/workflows/          CI-/APK-/Node-Release-Automation
docs/                       Lizenzleitfaden, Sicherheit, Evidenz, Aurion-Grenzen
```

Die vollständige Architektur, Grenzen und Beispielabläufe stehen in der [technischen Dokumentation](software_gpu/docs/ARCHITECTURE.md). Die ursprünglichen Quellbehauptungen sind zu Herkunftszwecken getrennt in [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md) archiviert und **nicht automatisch verifiziert**.

## Lizenz und Namensnennung

**Copyright (c) 2026 OuroborosCollective.**

Dieses Projekt steht, soweit die Rechte bei den genannten Rechteinhabern liegen, unter der **[PolyForm Noncommercial License 1.0.0](LICENSE.md)** (`PolyForm-Noncommercial-1.0.0`).

- **Nichtkommerziell:** Verwenden, untersuchen, ändern und unter den Lizenzbedingungen weitergeben.
- **Namensnennung:** Bei Weitergabe den [verpflichtenden Rechtehinweis](NOTICE) und die Lizenz bzw. ihren offiziellen Link mitgeben. Empfohlene sichtbare Quellenangabe: „Based on ARE SoftwareGPU Engine by OuroborosCollective“.
- **Kommerziell:** Nur mit **separater vorheriger schriftlicher Vereinbarung** mit den zuständigen Rechteinhabern; die öffentliche Lizenz erteilt diese Erlaubnis nicht.

Die Lizenz ist **source-available, nicht OSI-zertifiziertes Open Source**. Rechte an Drittkomponenten bleiben unberührt. Anfragen für kommerzielle Lizenzierung: [Lizenzleitfaden](docs/LICENSING.md). Beiträge: [CONTRIBUTING.md](CONTRIBUTING.md).

## Aurion: bewusst isoliert

Eine eventuelle Verwendung bei Echoes of Aurion ist nur als **read-only Offline-Render-/Benchmark-Worker** vorgesehen. Es gibt **keine** Liveintegration in die kanonische Spielwelt, Physik-Autorität oder 100-ms-Ticksteuerung. [Schnittstellenvertrag](docs/AURION_OFFLINE_ADAPTER_CONTRACT.md).

[Projektstatus und CI-Evidence](PROJECT_STATUS.md) · [Projektüberblick (DE/EN)](docs/PROJECT_OVERVIEW.md)

## MIHA CPU training integration

[Workflow, runner requirements and outputs](docs/MIHA_CPU_TRAINING.md): pinned Hugging Face CPU-LoRA training with canonical/Atomic readback, unchanged 16-GiB and longest-example gates, real training-loss charts, checkpoints and optional candidate upload. Open the generated `training_metrics.html` for a readable chart and exact observations. ARE SoftwareGPU renders metrics on CPU; tensor training remains in CPU PyTorch.

## Experimenteller Flächenplaner

Der ausdrücklich wählbare Backend-Pfad `tiles-plan` ergänzt Flächenklassifikation,
deklarierte Vertex-Color-Batch-Shader und einen vierfarbigen Graph-Nachweis.
Standard bleibt `tiles`; kleine Primitive können auf den Referenzpfad zurückfallen.
[Bedienung, Verträge und Grenzen](docs/SURFACE_PLANNER.md).

```bash
python -m software_gpu.benchmarks.compare_surface_plans --output-dir surface-plan-results --repeats 15 --pixels 256 --ablation
```

Die [SoftwareGPU Workbench](plugins/softwaregpu-workbench/README.md) enthält
das wiederverwendbare Plugin für echte Regressionen, begrenzte Benchmarks,
Quellhash-Audit, Ablationsanalyse, Renderer-Kalibrierung und CPU-Finetuning-Preflight.
