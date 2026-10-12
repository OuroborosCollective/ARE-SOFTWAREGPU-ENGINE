# Übergabe: reproduzierbare Referenzarena und Renderer-Phasenprofil

**Stand:** 2026-10-12 · Branch `feat/reference-arena-frame-timings-20261012` · Basis: `main` bei `1b74820` (`Merge pull request #35...`)

## Ergebnis in Kürze

- Eine browserfähige **Three.js-Referenzarena** lädt alle sechs verifizierten GLB-Anhänge. Vier Figuren laufen mit Originalclips; Baumstamm und Granitfelsen sind statisch. Die GLB-Materialien und eingebetteten Texturen bleiben erhalten; die Kamera ist perspektivisch.
- Der native Läufer zeichnet nun **Pose (animiert/statisch), Dreiecksvorbereitung/Beleuchtung, Übergabe, Setup, Raster, MSAA, AA und Bio-Binning pro Frame** auf. Zusätzlich werden die summierten Worker-Ausführungszeiten je Rendereroperation erfasst, damit die überlappende Frontier-Wallzeit nicht fälschlich als isolierte Stufenzeit ausgelegt wird.
- `tools/benchmark_models.py` kann `animated4`, `static2` und `arena6` gezielt in einem reproduzierbaren Lauf messen. Es zeichnet Median, p95, Maximum, Slow-Frames über 16,7 ms, Bilder/Framehashes, Vollbufferparität sowie Quell- und Originalmodellhashes auf.
- Die nachweislich größte Workerarbeit – das Raster – erhielt eine gezielte, semantikerhaltende Optimierung: **Top-left-Kanten-Inklusivität wird einmal pro vorbereitetem Dreieck statt je Sample bestimmt.** Die Raster-/Bio-Paritätstests bleiben bitgenau.
- Die tatsächlich gemessene Beschleunigung ist **begrenzt**: Arena6 Median 42,33 → 41,28 ms (−2,48 %); das Bio-Ergebnis bleibt deutlich über 16,7 ms. Das ist ein gemessener Fortschritt, keine Behauptung einer fertigen 60-FPS-Spielepipeline.

## Vorher/Nachher (15 alternierende Paare, 256×256, Tile 32, 4 Worker)

| Workload | Native Baseline median vorher → nachher | Bio median vorher → nachher | Bio p95 vorher → nachher | Bio max vorher → nachher | Bio-Speedup nachher (Medianverhältnis) | Slow-Frames nachher >16,7 ms |
|---|---:|---:|---:|---:|---:|---:|
| `animated4` (vier animierte Figuren) | 85,55 → 88,67 ms | 36,81 → 36,26 ms (−1,47 %) | 46,10 → 49,28 ms | 48,84 → 71,33 ms | 2,45× | 15/15 |
| `static2` (Baumstamm + Felsen) | 23,61 → 22,25 ms | 10,94 → 10,49 ms (−4,04 %) | 13,43 → 16,45 ms | 14,11 → 17,64 ms | 2,12× | 1/15 |
| `arena6` (4 Figuren + 2 Umfeldobjekte) | 106,34 → 101,44 ms | 42,33 → 41,28 ms (−2,48 %) | 47,50 → 57,34 ms | 47,61 → 61,73 ms | 2,46× | 15/15 |

Vorher- und Nachher-Benchmark wurden auf demselben Sandbox-Host, mit denselben sechs nach SHA-256 verifizierten Modelloriginalen, derselben Arena-Geometrie, Konfiguration und 15 Samplezeitpunkten ausgeführt. Jeder Lauf bestätigt nach der Messung keine Quellenänderung während des Laufs und keine Abweichung der geprüften GLB-Hashes. **Die vollständigen Framepuffer entsprechen pro Fall bitgenau der seriellen Referenz (`full_buffer_parity=true`);** es liegen 15 Frame-Hashes je Fall vor. Der Lauf dauert jeweils rund 11 Sekunden für alle drei ausgewählten Cases.

Messungen eines geteilten Hosts mit 15 Paaren sind beobachtete Workload-Werte, keine gerätespezifische FPS-Garantie und kein statistischer Konfidenzbereich. Die höheren p95-/Maxima nachher, besonders das einzelne animierte 71,33-ms-Maximum, müssen als **Langsamframes und Host-/Lastempfindlichkeit** mitgelesen werden; der Median allein beschreibt sie nicht.

## Interpretation der Phasenmessung

In der optimierten `arena6`-Messung beträgt die mediane Raster-Workerarbeit 28,56 ms (Summe der gemessenen Workerintervalle), gegenüber rund 0,46 ms MSAA- und 2,55 ms AA-Workerarbeit. Das macht Raster zu einer sinnvollen Optimierungsstelle. Die Workerarbeitszeiten summieren über parallele Arbeit und sind **keine Wandzeit**.

Bei der Bio-Frontier-Welle laufen Raster, MSAA und AA abhängig von Tile-Abhängigkeiten überlappend. Für diese drei `*_ms`-Wallfelder wird dieselbe gemeinsame Wellen-Wandzeit berichtet. **Diese Felder niemals addieren oder als isolierte Phasendauern interpretieren.** Als echte Latenz gilt `frame_total_ms`; für den Rechenarbeitsanteil dienen die separat ausgewiesenen `*_worker_work_ms`-Summen. Die serielle Referenz hat sequenzielle Wellenintervalle.

## Referenzviewer und ursprüngliche Spielepipeline

`reference_arena/` ist eine rein visuelle Three.js-Ansicht mit WebGL, Perspektive, PBR-Licht, GLB-Originaltexturen/-materialien, animierten Clips und Orbit-Steuerung. Sie ist ein nützlicher visueller GLB-Referenzpfad, **kein dritter Timing-Backend**. Ihr browserseitiger FPS-Zähler ist ausdrücklich keine native Messung.

Der vorhandene native GLB-Renderpfad bleibt dagegen absichtlich ein kontrollierter, orthografischer, diagnosebeleuchteter CPU-Vergleich: originale PBR-/Texturzuweisungen und perspektivische native Projektion sind darin noch nicht integriert. Die browserseitige und native Ausgabe werden daher nicht als pixelgleiche Renderings ausgegeben. **Perspektivisch korrekte native Texturen/Materialien** bleiben der nächste Funktionsschritt; sie benötigen einen klar versionierten C++-Attribut-, Projektions- und Materialvertrag sowie neue Referenz-/Paritätstests. Die kleinen Messverbesserungen rechtfertigen keine LOD-, Sichtbarkeits- oder Pixelarbeits-Reduktion, die hier nicht getestet wurde.

## Reproduktion

1. Lege die vom Projekt verwaltete ZIP bereit (die Quellen bleiben privat/lokal):

   ```sh
   python tools/install_reference_arena_assets.py /pfad/SoftwareGPU_Referenzarena_GLB_Modelle.zip
   ```

   Der Installer prüft Größe und SHA-256 jedes ausgewählten GLB gegen `evidence/original-model-manifest-v1.json`; `reference_arena/assets/*.glb` wird ignoriert und **nicht** committet.

2. Starte den visuellen Viewer aus dem Repositoryroot:

   ```sh
   python -m http.server 8000 --directory reference_arena
   ```

   Öffne `http://localhost:8000/` in einem Browser mit Internetzugang (Three.js 0.180.0 und Addons werden von jsDelivr geladen).

3. Wiederhole den nativen Vorher-/Nachher-Szenenvergleich:

   ```sh
   python tools/benchmark_models.py \
     --assets /pfad/zu/den/Originalmodellen \
     --output-dir /tmp/reference-arena-results \
     --phase bench --cases animated4,static2,arena6 \
     --repeats 15 --seconds 600
   ```

4. Führe die regressionskritischen Tests aus:

   ```sh
   python -m unittest \
     software_gpu.tests.test_workrooms \
     software_gpu.tests.test_bio_workrooms \
     software_gpu.tests.test_native_raster \
     software_gpu.tests.test_model_probe -v
   ```

5. Vorher-/Nachher-Receipts und komprimierte 256×256 Frame-/Depth-Arrays liegen unter `evidence/reference-arena-{before,after}-...-20261012.*`. Die JSONs enthalten native Rohreceipts, Samplezeitpunkte, Timingprofile, Konfiguration, Umgebungs-/Quellhashes und die sechs benutzten Assethashes. Die sechs Original-GLBs selbst sind nicht eingecheckt.

## Validierung dieses Changesets

- **26 Tests bestanden:** Workrooms, Bio-Workrooms, Native-Raster, GLB-Laden/Skinning/Animation, nativer Puffer, fehlerhafte Receipts und exakte Workerparität.
- **Vollständige Projektsuite bestanden:** `python -m unittest discover -s software_gpu/tests -p 'test_*.py'` → 282 Tests bestanden, 2 übersprungen (184,2 s).
- Python- und Viewer-JavaScript-Syntaxprüfung bestanden.
- Der Viewer wurde im Sandbox-Browser geprüft: **6/6** Modelle geladen; vier Animation-Dropdowns, geladene Originalmodelle und sichtbare Arena.
- Beide Benchmarkläufe enthielten `animated4`, `static2`, `arena6`, je 15 Paare und exakt gleiche finale Puffer; vor/nach den Messungen bestand jeweils Quell-/Asset-Hashkonsistenz.
- `git diff --check` bestanden; die GLB-Dateien sind per `.gitignore` geschützt.

## Handoff / nächste sinnvolle Schritte

1. Draft-PR reviewen; insbesondere beachten, dass die Rasteroptimierung einen kleinen Mediangewinn bei `arena6`, aber keine stabile 60-FPS-Zielerreichung bringt.
2. Auf einem weniger variablen oder dedizierten Runner denselben gepaarten Benchmark wiederholen; dabei p95/Maximum und nicht nur Median bewerten.
3. Anschließend in einem separaten Design-/Implementierungsschritt native Perspektivprojektion plus perspektivisch korrekte UV-Interpolation und Originaltexturen/PBR-Materialien ergänzen. Alpha, Normalmaps, Sampler-/Mip-Verhalten und Farbmanagement jeweils explizit spezifizieren und die bestehende Diagnose-/VertexColor-ABI unverändert halten.
4. Nach der Funktionsintegration dieselbe Arena, gleiche Originalhashes, Basis-/Bio-Verfahren und einen perspektivischen Referenzvertrag erneut messen; Textur- und Perspektivkosten separat ausweisen.
