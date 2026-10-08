# ARE SoftwareGPU Engine

CPU-only Software-Rasterizer und Compute-Prototyp fuer reproduzierbare Grafik-/Matrixoperationen. Der Quellcode wurde aus dem vom Inhaber bereitgestellten TAR-Archiv **SoftwareGPU 1.2.0** ueber einen SHA-256-gebundenen GitHub-Actions-Import uebernommen.

**Status: Forschungs- und Entwicklungsprojekt. Kein GPU-Treiber, kein Ersatz fuer CUDA, DirectX 11 oder OpenGL ES auf Systemebene.** Die D3D11-artige Python-API emuliert eine Renderpipeline; es existiert kein Nachweis, dass beliebige Windows-Spiele oder CUDA-Trainingsframeworks damit unveraendert laufen.

## Enthalten
- NumPy-basierte CPU-Matrixoperationen, elementweise Aktivierungen und SIMT-artige Test-Kernels
- CPU-Rasterizer, Software-Shader, Depth-Buffer, 4x MSAA, FXAA und HDR-Demos
- VPS/CPU-Auslastungstelemetrie und Benchmarks ohne hardwarebeschleunigte GPU
- HTTP- und TCP-Prototyp auf Loopback; Netzwerk-Clients in Python, JS, C, C++, C#, Go und Rust
- Experimentelle Android-/OpenGL-ES- und MMORPG-Integrationen

Client-Beispiele und experimentelle Adapter sind **keine** Nachweise vollstaendiger Plattform- oder Sprachkompatibilitaet.

## Lokal pruefen

Voraussetzung: Python 3.11 oder 3.12 und eine CPU.

```bash
python -m pip install "numpy>=1.20,<3"
python -m unittest discover -s software_gpu/tests -v
python main.py --help
python main.py --info
```

Die GitHub-Actions-Regressionen testen Ubuntu und Windows mit Python 3.11/3.12. Das ist weder ein nativer DirectX-Test noch ein Android-Deploymenttest.

## Source-Provenienz
- Originalarchiv: `aistudio_agent_environment-805fd56f-4455-4da9-b5ab-a0fe51f950c8-2026_10_08T17_31_27_601Z.tar`
- Erwarteter Archiv-SHA-256: `b8b44a39b46ecfb50a2de121b2534c5d9912fccda2b1b0475faf194fe8e589b8`
- 62 selektiv importierte UTF-8-Quelldateien. Temporaere Bytecode-Dateien, Links, generierte Bilder und Binaerartefakte wurden **nicht** entpackt.
- Historische Importpruefsummen: [evidence/source-manifest.json](evidence/source-manifest.json)
- Original-Dokumentation (unueberpruefte Behauptungen): [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md)
- Reproduzierbare Importquelle: [scripts/import_source_archive.py](scripts/import_source_archive.py)

Die Manifest-Hashes dokumentieren den **urspruenglichen Importstand**; spaetere explizite Korrekturen muessen nicht bytegleich zu diesen Quellen bleiben.

## Netzwerk- und Produktionsgrenze

**HTTP/TCP-Server nicht oeffentlich freigeben.** Der experimentelle Dienst bietet derzeit keine verpflichtende Authentisierung, TLS-Terminierung, Mandantentrennung und keine hinreichend strengen Payload-/Kostenlimits. Der Standardbind ist `127.0.0.1`. Vor externer Bereitstellung sind separate Security-Gates erforderlich.

## Aurion

ARE SoftwareGPU wird nicht als zweite Spielwelt-, Persistenz-, Physik- oder Tick-Authority eingebunden. Eine spaetere Aurion-Anbindung darf nur **isolierte CPU-Offline-Render-/Benchmark-Ergebnisse** mit reproduzierbaren Eingabehashes, Limits und Evidence-Receipts zurueckgeben. Keine Schreibrechte auf kanonischen World State.

Details und offener Nachweisbedarf: [PROJECT_STATUS.md](PROJECT_STATUS.md).
