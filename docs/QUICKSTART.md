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
