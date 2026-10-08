# ARE SoftwareGPU Engine — Technische Architektur

**System:** CPU-basierte Rendering- und Compute-Runtime. **Status:** Forschungs-/Entwicklungsprojekt, kein GPU-Gerätetreiber.

## 1. Pipeline und Eigentümerschaften

```text
3-D Vertices + Indices
        |
        v
Python Vertex Shader -> primitive assembly + coarse clipping/rejection
        |
        v
Screen-space triangles, edge functions, depth
        |
        +--> bands    (alter horizontaler CPU-Referenzpfad)
        |
        +--> tiles    (2-D-Triangle-Binning, NumPy-Coverage/Depth)
        |
        +--> tiles-jit  (optional: Numba/LLVM-Coverage/Depth auf CPU)
        |
        v
Python Fragment Shader (sichtbare Pixel; nicht LLVM-kompiliert)
        |
        v
RGBA-Framebuffer + Float32-Depth
        |
        v
Optional 4x MSAA / FXAA / HDR / Bloom / Datei-Export
```

Die primären Pfade liegen in `graphics/rasterizer.py`, `graphics/tile_backend.py`, `graphics/compiled_tile.py`, `graphics/framebuffer.py`, `graphics/postprocess.py` und `graphics/shader.py`.

- **Tile-Ownership:** Jede Kachel hat disjunkte Farb-/Tiefenregionen, erhält nur überlappende Dreiecke und bearbeitet diese in ursprünglicher Einreichungsreihenfolge. Mehrere Worker bearbeiten voneinander unabhängige Kacheln.
- **Vektorisierung:** NumPy führt Coverage und Tiefentest auf CPU-Arrays aus. Das allein belegt **nicht**, welche AVX-/NEON-Maschineninstruktionen die konkrete CPU benutzt.
- **Opt-in JIT:** Numba/LLVM beschleunigt CPU-Inner-Loops (`nogil=True`, `fastmath=False`), während frei definierbare Python-Fragmentshader im Python-Interpreter bleiben. Es gibt keinen HLSL-/GLSL-/CUDA-Compiler.
- **MSAA:** Der `MSAAFramebuffer` speichert 4 Subpixel-Samples und kann diese mit `uint16`-Akkumulation ohne Float32-Vollkopie auflösen. Das ist nicht mit Direct3D-Konformität gleichzusetzen.
- **Grenze:** Eine „deterministische“ Tile-Reihenfolge bedeutet nicht automatisch bitgleiche Ausgabe auf *jeder* CPU, Floating-Point-Plattform und Library-Version. CI vergleicht definierte lokale Szenen.

## 2. Module und Flächen

| Verzeichnis | Aufgabe | Einordnung |
| --- | --- | --- |
| `core/` | CPU Device-/Memory-Modell, Output-Pfade, VPS Governor | Core und Effekte |
| `compute/` | Generator-SIMT, Kooperations-/Barrieresimulation, NumPy-Kernels | Core/Forschungsruntime |
| `graphics/` | Software-Rasterizer, Framebuffer, Shader, Postprocessing | Produktionskandidat + Core |
| `benchmarks/` | Lastversuche und A/B-CPU-Vergleich mit Bildparität | Tests/Evidence |
| `network/` | HTTP/TCP-Dienste und Request-Dispatcher | Unsichere experimentelle Effektfläche |
| `clients/` | Sprachclients in Python, JS, C/C++, C#, Go, Rust | Demonstrationsadapter |
| `mobile/` | Android-IPC und OpenGL-ES-artige Python-Prototypen | Unverifizierte Plattformprojektion |
| `directx/` | Direct3D-11-artige Python-Objekte/Demo | API-Simulation, kein Windows-Treiber |
| `integrations/` | Image-Filter, Blender, MMORPG-Beispiele | Experimentelle Adapter |
| `tests/` | CPU-Grafik-, Mathematik-, Netzwerk- und Regressionstests | Evidence |

**Persistenzgrenze:** Nur erzeugte Bilder/JSON-Reports im lokalen Ausgabeverzeichnis; keine autoritative Aurion-Weltzustands- oder Spielstandsverwaltung. **Runtime-Grenze:** Eine Datei im Repository ist kein Nachweis, dass diese auf einem Endgerät oder Server als Produktivdienst aktiv ist.

## 3. Starten, Messen und Prüfen

```bash
python -m pip install -e .
python -m unittest discover -s software_gpu/tests -v
python -m software_gpu.benchmarks.compare_tile_backends --workers 1 --repeats 3
```

Optional Numba/LLVM:

```bash
python -m pip install -e ".[jit]"
python -m software_gpu.benchmarks.compare_tile_backends --workers 2 --repeats 3 --jit
```

Benchmarks nutzen deterministische Mesh-Fixtures und vergleichen historische Bänder, NumPy-Tiles und optional LLVM-Kacheln **auf CPU**. Nachweisstand: [RENDER_OPTIMIZATION_EVIDENCE.md](../../docs/RENDER_OPTIMIZATION_EVIDENCE.md). Eine hardwareübergreifende Leistungszusage ist nicht möglich.

## 4. Sicherheit und Plattformgrenzen

- Netzwerkservices besitzen derzeit keine verpflichtende Authentisierung, TLS-Terminierung und ausreichenden CPU-/RAM-/Payload-Schutz. [Sicherheit](../../docs/SECURITY_AND_LIMITS.md).
- Die Python-ähnlichen DirectX-/CUDA-Bezeichner vermitteln **keine** native API-Kompatibilität für existierende Spiele oder LLM-Frameworks.
- Android-Code ist vorhanden, es fehlt aber ein nachgewiesener Android-Geräte-/Emulator-Test und ein vollständiger Build-/Signierungsprozess.
- Multi-Sprach-Client-Beispiele belegen noch keine dauerhafte API-/ABI-Kompatibilität.
- Für Aurion ist ausschließlich ein separater read-only Offline-Worker denkbar; niemals eine zweite kanonische Gameplay-, Physik- oder 100-ms-Tick-Authority. [Aurion-Vertrag](../../docs/AURION_OFFLINE_ADAPTER_CONTRACT.md).

## 5. Quelle und Lizenz

Die ursprünglichen TAR-Quellen sind [durch Prüfsummen dokumentiert](../../evidence/source-manifest.json); die historische Werbedokumentation findet sich getrennt im [Upstream-Archiv](../../docs/UPSTREAM_README.md). Unbestätigte Performance- und GPU-Ersatz-Aussagen sind **nicht** als Fakt zu übernehmen.

Copyright (c) 2026 OuroborosCollective. [PolyForm Noncommercial License 1.0.0](../../LICENSE.md) mit [Required Notice](../../NOTICE). Nichtkommerzieller Zugang unter Lizenzbedingungen; kommerzielle Verwertung erst nach gesonderter schriftlicher Freigabe. [Lizenzleitfaden](../../docs/LICENSING.md).
