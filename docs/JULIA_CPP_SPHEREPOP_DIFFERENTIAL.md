# Julia ↔ C++17: Doppler und SpherePop Impact Waves (CPU-Forschung)

**Basis:** `main` 9d258634c0ef63725c2b4ef1dcc051c5f8699ebe (21.10.2026). Experimenteller, explizit isolierter Forschungs-Workflow. Keine Änderung des produktiven C++-Rasterkerns; Julia ist **keine** Runtime-Abhängigkeit und wird nicht in Render-Frames geladen.

## Reale Tests

- `native/raster/julia_cpp_differential_driver.cpp` ruft bestehende `doppler_only::classical_factor`, `experimental::doppler_factor` und `render_radial_cag_spherepop` auf. Die originalen C++17-Implementierungen werden nicht nachgebaut.
- `software_gpu/research/julia_cpp_differential.jl` hat eine **unabhängige Julia-Implementierung** der radialen Prioritätswarteschlange und Farbanpassung. Es vergleicht 5 Doppler-Faktoren und 3 × 16 tatsächlich finalisierte Wellenbereiche einschließlich Ereignisreihenfolge, Emitter, Ankunftszeit, Farb-RGBA, Owner, Tinted-Flags, FNV-Eventidentität, Rejection-Zähler und Faktoraufrufe.
- Abgedeckte Varianten: klassischer direkter Doppler ↔ SpherePop-Doppler; SpherePop Impact Waves mit und ohne Faktor-Reuse sowie Effekt ausgeschaltet. C++ verwirft überhöhte Geschwindigkeit, ungültige Sichtlinie und NaN-Depth; Fehlereingaben dürfen keine Farbe verändern.
- Die native und unabhängige Julia-Implementierung verwenden dieselben Eingabewerte, aber **nicht denselben Algorithmus-Code**. Float64-Mathematik wird mit enger absoluter/relativer Toleranz geprüft; Bytegenauigkeit gilt nur für finale RGBA- und Event-Metadaten, nicht für frei umstellbare Gleitkommarechnungen.
- **Wolfram** ist ein drittes, unabhängiges **exaktes Mathematikorakel**. Am 21.10.2026 bestätigt: `FullSimplify[{120/(120-30),120/(120+30),120/(120-0),120/(120-30/Sqrt[2]),120/(120+30/Sqrt[2]),Sqrt[2]/120}]` → `{4/3,4/5,1,4(8+Sqrt[2])/31,4(8-Sqrt[2])/31,1/(60 Sqrt[2])}`. Ein live zugeschalteter Wolfram-Server in jeder CI ist absichtlich **nicht** nötig. Die Julia-Assertions prüfen die ersten fünf mathematischen Werte zusätzlich.
- Kein Timing-Benchmark und kein FPS-/GPU-Paritätsbeleg: Das bestehende `compare_spherepop_wave_frames.py` bleibt dafür zuständig und misst weiterhin den vollständigen CPU-Draw. Julia-Kompilierung wird nicht mit C++-Framezeiten vermischt.

## CI und reproduzierbarer Aufruf

```bash
g++ -std=c++17 -O3 -fno-fast-math -ffp-contract=off -Wall -Wextra -Werror native/raster/julia_cpp_differential_driver.cpp -o /tmp/native-wave
julia --startup-file=no --history-file=no --compiled-modules=no software_gpu/research/julia_cpp_differential.jl /tmp/native-wave
```

Der separat pfadgefilterte GitHub-Workflow `julia-cpp-differential.yml` richtet Julia 1.10 auf Ubuntu mit festem SHA des Setup-Actions ein, verwendet keine Julia-Pakete und startet die C++-Binary tatsächlich. Die vollständigen vorhandenen Windows/Linux/Python-/LLVM-/Mesa-Gates müssen zusätzlich auf dem exakten PR-Head grün sein, bevor ein Merge vertretbar ist.

**Negativnachweise und Grenzen:** Das 4×4-Fenster ist absichtlich deterministisch und kein realer gerenderter GLB-Frame. Die native Wellenfunktion ist eine originale SpherePop-inspirierte Adaption, nicht die vollständige upstream SpherePop-Semantik. Hochgeladene Original-GLBs und deren Texturen bleiben lokal und werden nicht in diesem öffentlichen PR veröffentlicht. GLB-Tests und 15 A/B-Timingpaare sind ein separater Leistungsgate.

**Merge-Regel:** Ergebnis erst nach vollständiger exakter Head-CI und Readback als integriert kennzeichnen; dann genau eine append-only `Memory.md`-Zeile mit Änderung, Erkenntnis und Evidence.
