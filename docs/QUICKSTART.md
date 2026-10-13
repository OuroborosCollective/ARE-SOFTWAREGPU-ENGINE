# Erste Schritte / Getting Started

## Voraussetzungen

- Python **3.11 oder 3.12** (CI-getestete Versionen); Linux oder Windows
- CPU und installierbares NumPy; keine dedizierte GPU erforderlich
- `git`, eine Python-Umgebung und ggf. Zugriff auf Paketquellen

## Linux

```bash
git clone https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE.git
cd ARE-SOFTWAREGPU-ENGINE
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
software-gpu --help
software-gpu --info
```

## Windows (PowerShell)

```powershell
git clone https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE.git
cd ARE-SOFTWAREGPU-ENGINE
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\software-gpu.exe --help
.\.venv\Scripts\software-gpu.exe --info
```

## Reale Tests statt Annahmen

```bash
python -m unittest discover -s software_gpu/tests -v
python -m software_gpu.benchmarks.compare_tile_backends --workers 1 --repeats 3
```

Die Benchmarks vergleichen 1) historischen horizontalen Band-Renderer, 2) vektorisierte CPU-Tiles und optional 3) LLVM-JIT-Tiles auf **derselben** Maschine. Jede Fixture überprüft zusätzlich die Bild-/Tiefengleichheit.

Optionaler LLVM/Numba-CPU-Kern:

```bash
python -m pip install -e ".[jit]"
python -m unittest discover -s software_gpu/tests -v
python -m software_gpu.benchmarks.compare_tile_backends --workers 2 --repeats 3 --jit
```

JIT-Beschleunigung ist optional und nicht auf jeder CPU schneller. Der Benchmark führt einen Warm-up-Lauf aus; JIT-Kompilierungszeit gehört daher nicht zu den angegebenen Medianwerten.

## C++17, Gradio und mobile/Node-Begleitclients

- [Nativer C++17-Rasterizer](NATIVE_RASTER.md) und [AREMDL03 PBR-Originalmodell-Benchmark](native-pbr-arena-report-20261013.md): für die PBR-Dekodierung `python -m pip install -e ".[model-pbr]"`, zusätzlich verifizierte lokale Original-GLBs gemäß Modellmanifest.
- [Private Gradio CPU Arena](../plugins/gradio_arena/README.md): `python -m pip install -e ".[gradio-arena]"` und `python -m plugins.gradio_arena.app` nach Setzen sicherer `ARE_GRADIO_USER`/`ARE_GRADIO_PASSWORD`-Umgebungsvariablen. Lokal auf `127.0.0.1:7860`, **kein öffentlicher Hosting-Readback**.
- [Android-/Linux-/Windows- und npm-Release-Status](RELEASE_STATUS.md): Begleitclients verbinden sich mit einer separaten **HTTPS-Gradio-Instanz**; keine lokale native GPU im Android-Client, Linux/Windows brauchen Node 20+.

## Grafik-Demos

```bash
software-gpu --gaming
software-gpu --directx
software-gpu --filters
```

Die Flags starten **Python-Demos**, keine native DirectX-Spielkompatibilität. Ausgaben erfolgen im Arbeitsverzeichnis oder – falls gesetzt – im Verzeichnis aus `ARE_SOFTWAREGPU_OUTPUT_DIR`.

### Wichtig

- `software-gpu` ohne Argumente startet gemäß aktuellem CLI die Gesamtdemo. Für einen sicheren Einstieg explizit `--help` oder `--info` verwenden.
- `software-gpu --server` startet ein experimentelles HTTP/TCP-Subsystem. Nicht öffentlich exponieren: keine vollständige Authentisierung, keine harten Payload-/Compute-Quoten.
- Android-/Cross-Language-Beispiele sind experimentell und benötigen eigene ABI-/Geräteprüfung.

[Architektur](../software_gpu/docs/ARCHITECTURE.md) · [Tests und Evidence](RENDER_OPTIMIZATION_EVIDENCE.md) · [Sicherheit](SECURITY_AND_LIMITS.md) · [Lizenz](LICENSING.md)
