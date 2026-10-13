# ARE SoftwareGPU Engine — Projektüberblick / Project Overview

## Untertitel / Subtitle

**Deutsch:** CPU-basierte Software-Rasterisierung, vektorisierte Grafikberechnungen und reproduzierbare Benchmarks ohne dedizierte GPU.

**English:** A CPU-only software rendering and compute research engine with deterministic tiled rasterization and optional LLVM acceleration.

## Kurzbeschreibung / Short description

**DE:** ARE SoftwareGPU Engine erforscht, welche GPU-ähnlichen Grafik- und Compute-Aufgaben durch optimierte CPU-Software nachvollziehbar ausgeführt werden können. Sie kombiniert 2D-Tile-Binning, NumPy, eine optionale Numba/LLVM-CPU-Kernelstufe und Grafikfunktionen wie 4× MSAA/FXAA mit echten Vergleichstests. Der Fokus liegt auf Reproduzierbarkeit, Messbarkeit und dem Einsatz ohne dedizierte Grafikkarte.

**EN:** ARE SoftwareGPU Engine explores GPU-style graphics and compute techniques on commodity CPUs. The experimental Python renderer combines 2-D triangle binning, vectorized NumPy masks, optional LLVM-compiled CPU coverage and depth testing, and selected antialiasing/postprocessing effects. Regression tests compare real CPU-rendered images and performance.

## Zielgruppe / Who is it for?

- Entwickler und Forschende, die CPU-only Rasterisierung, Pixel- und Depth-Regressionen untersuchen.
- Hardware-unabhängige Testpipelines, die Bilder und Rechenmetriken ohne dedizierte GPU erzeugen.
- Game-Tooling-/Offline-Baking-Experimente mit streng getrennten Spielzustandsgrenzen.
- Lehr- und nichtkommerzielle Forschungszwecke unter den Bedingungen der Lizenz.

## Status / Status

| Experiment | Implementiert | Produktionsnachweis |
| --- | --- | --- |
| CPU Triangle- und Tile-Rasterisierung | Ja | Referenz-/Tile-Bildtests, Linux/Windows |
| LLVM/Numba CPU-Coverage-JIT | Optional | Linux/Windows CI, nicht allgemeine CPU-Beschleunigung |
| 4× MSAA und FXAA | Ja | Funktionstests, keine API-Konformität |
| Direct3D-11-/CUDA-artige Python-Adapter | Demo | Keine native API- oder Treiberkompatibilität |
| Android-WebView und Node-Clients | HTTPS-Client und automatisierter Paketbau | Kein Emulator-/Gerätelauf, Serveradresse erforderlich |
| LLM-Training ohne GPU | Kein vollständiger Stack | Kein PyTorch-Backend/Backprop-GPU-Ersatz |
| Aurion-Offline-Worker | Isoliert implementiert und getestet | Keine kanonische Aurion-Runtime-Anbindung |
| Native C++17 AREMDL03/PBR | Optional implementiert | CPU-Pufferparität, Original-GLB-Receipts; keine 60-FPS-Freigabe |
| Gradio Evidence Arena | Optionales, authentifiziertes Loopback-Frontend | Echter 64px-Worker und unautorisierter HTTP-401-Regressionstest |

Der CPU-Vergleich beobachtete in ausgewählten CI-Fixtures 1,51–1,73-fache Geschwindigkeit gegenüber einer älteren CPU-Streifenimplementierung. Daten und Einschränkungen: [Evidence](RENDER_OPTIMIZATION_EVIDENCE.md).

## Lizenz / Licensing

**Copyright (c) 2026 OuroborosCollective.** Nichtkommerzielle Nutzung unter [PolyForm Noncommercial 1.0.0](../LICENSE.md) mit [Pflichtvermerk](../NOTICE). Kommerzielle Nutzung nur nach separater schriftlicher Zustimmung der jeweiligen Rechteinhaber. Nicht OSI-Open-Source. [Details](LICENSING.md).

## Grenzen

Keine Hardware-GPU-Emulation auf Treiberebene, kein DirectX/CUDA-Ersatz, keine garantiert plattformidentischen Ergebnisse für beliebige Eingaben und keine Freigabe ungesicherter Netzwerkdienste. [Security](SECURITY_AND_LIMITS.md).
