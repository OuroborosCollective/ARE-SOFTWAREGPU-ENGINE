# ARE SoftwareGPU Engine — Forschung zum Ansehen und Nachmessen

> **Real CPU pixels. Deterministic evidence. No GPU-driver claims.**
>
> Eigenständige CPU-Grafikforschung von [OuroborosCollective](https://github.com/OuroborosCollective), source-available unter [PolyForm Noncommercial 1.0.0](../LICENSE.md).

![Echte Offline-Renderstichprobe aus der Originalmodell-Arena](../evidence/native-pbr-20261013/original-arena-smoke.png)

*Eine vorhandene, in der Repository-Evidence gespeicherte Renderstichprobe; kein interaktiver Live-Dienst und kein GPU-Leistungsbeweis.*

## Was hier tatsächlich läuft

- **C++17 + CPU:** optionale native symbolische Workrooms, Modellpose, perspektivisches Clipping und begrenztes AREMDL03/Metallic-Roughness-PBR einschließlich originaler eingebetteter GLB-Texturen.
- **Python-Grafikreferenz:** Framebuffer, strikt getestete Tiefe, Tiles, optionales Numba/LLVM, 4× MSAA/FXAA und Benchmarks.
- **Echte Modell-Arena:** sechs manifestgebundene Original-GLBs, vier animierte Figuren plus Umgebung. Die Binärdateien bleiben außerhalb von Git; die [Three.js-Referenz](../reference_arena/README.md) benötigt lokale Installation und ist **kein** nativer Benchmark.
- **Gradio:** optionale authentifizierte Loopback-Oberfläche für reproduzierbare prozedurale Offline-Renderjobs samt überprüften BMP-/Receipt-Hashes. [Startanleitung](../plugins/gradio_arena/README.md).
- **Begleitclients:** Android-Debug-APK sowie Node-basierte Linux-/Windows-Launcher und npm-Paket. Sie verbinden sich mit einem **separat erreichbaren HTTPS-Gradio-Server**, führen nicht selbst den C++17-Kern aus.

## Nachvollziehbare Zahlen statt Werbeversprechen

Der [PBR-Arenabericht](native-pbr-arena-report-20261013.md) protokolliert gepaarte CPU-vs.-CPU-Wandzeiten, komplette Frame-/Depth-Parität, Quellhashes und Umgebungsmerkmale. Die große animierte Arena verfehlt im berichteten Hostlauf weiterhin das 16,7-ms-Framebudget. Die Messwerte belegen **weder Hardware-GPU-Parität noch allgemeine 60 FPS**.

## Selbst ausprobieren

| Einstieg | Link |
| --- | --- |
| Python CPU-Engine | [Schnellstart](QUICKSTART.md) |
| Gradio-Offlinearena | [Sicherer lokaler Start](../plugins/gradio_arena/README.md) |
| Native Modell-/PBR-Evidence | [Mess- und Testbericht](native-pbr-arena-report-20261013.md) |
| GLB-Visualreferenz | [Three.js-Arena](../reference_arena/README.md) |
| Android-, Linux-/Windows- und npm-Clients | [GitHub Releases](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/releases) — nur dort vorhandene Assets als veröffentlicht betrachten |
| Live-Release-Gates | [Status und Einschränkungen](RELEASE_STATUS.md) |

## Für Entwickler, Lehrende und Forschende

Interessante Fragestellungen: Welche CPU-Rasterstufen profitieren von Tile-Binning? Wo entstehen Float32-Rundungsunterschiede? Was kosten Skinning und perspektivisch korrektes PBR auf einer CPU? Wie trennt man Benchmarkmessung von visueller Demo und Gameplay-Autorität?

Beiträge mit **reproduzierbarer Geometrie, Quellstand, tatsächlich gemessenen Rohwerten, vollständiger Farb-/Tiefenparität und Negativfällen** sind willkommen. Siehe [CONTRIBUTING.md](../CONTRIBUTING.md). Externe Code-Rechte müssen vor Übernahme geklärt werden.

**Grenzen:** keine NVIDIA-/CUDA-/Vulkan-/DirectX-Treiberersetzung, keine belegte Hardware-GPU-Beschleunigung, keine öffentliche freie Renderdienst-Instanz und keine direkte Aurion-Spielwelt-Autorität. [Lizenz](LICENSING.md) · [Sicherheit](SECURITY_AND_LIMITS.md).
