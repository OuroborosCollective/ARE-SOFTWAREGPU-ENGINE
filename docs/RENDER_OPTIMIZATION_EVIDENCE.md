# ARE SoftwareGPU: wissenschaftlich begruendete CPU-Rasteroptimierung

Stand: 2026-10-08. Dieses Dokument trennt **Forschung**, **implementierten Code** und **gemessene Nachweise**.

## Abgeleitete Implementierung
1. **Sort-middle, 2-D-Tile-Binning:** Jede Kachel erhaelt nur die geometrisch ueberschneidenden Dreiecke in urspruenglicher Reihenfolge. Die Kacheln schreiben in disjunkte Z-/Farbpufferregionen. Bereits dargestellte Geometrie wird nicht durch andere Kacheln ueberschrieben.
2. **NumPy-CPU-Vektormasken:** Pixel-Coverage und Early-Z werden tileweise ueber ufuncs berechnet. Python-Shadercallbacks pro tatsaechlich sichtbarem Pixel bleiben erhalten. Die GIL begrenzt die Parallelitaet dieser Callbacks.
3. **Optional Numba/LLVM CPU JIT:** Ein `njit(cache=True,nogil=True,fastmath=False)` Kernel berechnet Coverage, baryzentrische Gewichte und Early-Z. Die JIT-Option `tiles-jit` wird nur nach expliziter Installation von `software_gpu[jit]` aktiviert. Python-Shader oder CUDA werden dadurch **nicht** kompiliert. Konkrete AVX-/NEON-SIMD-Instruktionsnutzung ist nicht nachgewiesen.
4. **4x MSAA uint16 resolve:** Integer-Akkumulation von vier uint8-Kanaelen, arithmetisch identisch zum bisherigen Float32-Mittel mit Trunkierung. Geringerer temporaerer Speicherbedarf.
5. **Referenz erhalten:** `backend="bands"` laesst sich fuer Benchmark und Pixel-/Tiefenvergleich aktivieren.

## CI und Wiedervorlage
- **Source head:** `a14be371f60c4dcb8243d4f47bcacc56cba95ce8`
- **GitHub Actions:** https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/37834676696
- **Testscope:** Ubuntu/Windows je Python 3.11 und 3.12; LLVM-JIT separat auf Ubuntu/Windows mit Python 3.12; Wheel-Installation und CLI ausserhalb des Checkouts. 31 Standardtests, 33 mit Numba; Windows uebergeht nur den POSIX-UDS-Test.
- **Benchmarkverfahren:** Drei reale, seeded Mesh-Fixtures: (128 px, 160 kleine Dreiecke), (128 px, 8 grosse Dreiecke), (256 px, 320 kleine Dreiecke). Wiederholungen: 2 nach einem Warm-up. Medium: GitHub hosted x86_64 Ubuntu, Python 3.12; separate Runner, daher Ergebnisse nicht zu einem einzelnen direkten A/B-Lauf zusammensetzen.
- **NumPy tile vs. band (1 Worker):** Speedup 1.515x, 1.572x, 1.511x.
- **Numba tile vs. band (2 Worker):** Speedup 1.726x, 1.655x, 1.693x.
- **Qualitaet:** Farb-Buffers bitgleich, maximale Tiefenabweichung 0.0 in allen sechs Benchmarkvergleichsszenarien. Zusaetzliche Unittests pruefen 8/16/32/64-Pixel-Kacheln, Mehrworker-Ausgabe, wiederholtes Rendern und MSAA-Resolve.

**Grenzen:** Keine formale Profilierung von Cache-Misses, CPU-ISA-Disassembly, Prozess-/Speicherlimits, Echtzeit-FPS, DirectX/CUDA-Kompatibilitaet, Android-Deployment oder Vergleich mit Mesa llvmpipe auf identischer Hardware. JIT-Kompilierungszeit wird im Benchmark als Warm-up nicht mitgezaehlt. Auf anderen CPUs kann eine Variante langsamer sein.

## Primaerquellen und Fachgrundlage
- [Mesa LLVMpipe](https://docs.mesa3d.org/drivers/llvmpipe.html): LLVM-Software-Rasterisierung und Multicore-CPU, Vergleich als spaeteres externes Benchmarkziel.
- [Intel ISPC Performance Guide](https://ispc.github.io/perfguide.html): Datenlokalitaet, Struktur-von-Arrays, Tile-Iteration, ISA- und SIMD-Optimierungsgrundsaetze. ISPC wurde **nicht** als Compiler integriert.
- [Frolov/Galaktionov/Barladyan (2020): Comparative study of high performance software rasterization techniques](https://consensus.app/papers/comparative-study-of-high-performance-software-frolov-galaktionov/510240fe4d1f568a9eb2c0ecf1a4f21b/): Vergleich von CPU-Rasteralgorithmen, Speicherkonfiguration, Thread- und Instruktionsparallelismus.
- [Python threading documentation](https://docs.python.org/3/library/threading.html): GIL-Grenzen reiner Python-Threadschleifen.
- [DiffTaichi (ICLR 2020)](https://arxiv.org/abs/1910.00935): Beispiel eines GPU/CPU-Zielsystems mit kompilierten parallelen Kerneln; es ist **keine** Runtime-Abhaengigkeit dieses Projektes.

## Release-Einschraenkung
Kein GPU-Geraet notwendig. Trotzdem darf die vorhandene experimentelle HTTP/TCP-Schnittstelle ohne verbindliche Authentisierung, Payload-/RAM-/CPU-Limits und TLS nicht fuer untrusted Clients freigegeben werden. Der Aurion-Authority-Tick- und Weltzustand bleibt ausserhalb dieses Projekts.
