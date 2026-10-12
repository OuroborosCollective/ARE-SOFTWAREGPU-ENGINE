# Übergabe: reproduzierbare Referenzarena und Renderer-Phasenprofil

**Stand:** 2026-10-12 · Branch `feat/reference-arena-frame-timings-20261012` · aktueller PR-Commit `814a293` · Ziel: Draft-PR #48 gegen `main`

## Ergebnis in Kürze

- Eine browserfähige **Three.js-Referenzarena** lädt sechs verifizierte GLB-Modelle: vier animierte Figuren sowie Baumstamm und Granitfelsen. Originalmaterialien und eingebettete Texturen bleiben im Viewer erhalten; die Kamera ist perspektivisch.
- Der native Pfad ergänzt den unveränderten orthografischen `AREMDL01`-Vertrag um das versionierte Profil **`AREMDL02`**: explizite Look-at-/FOV-/Near-/Far-Kamera, homogene Perspektivprojektion, Sechs-Ebenen-Frustum-Clipping und vor dem Worker-Dispatch angepasste Dreieckstopologie.
- Der Native-Benchmark trennt animierte Figuren (`animated4`), statische Umgebung (`static2`) und die kombinierte Arena (`arena6`). Er berichtet Median, p95, Maximum, Frame-Stufen, langsame Frames, Framehashes, Vollpufferparität sowie Quell- und Assethashes.
- Die frühere orthografische Rasteroptimierung berechnet die Top-left-Kanten-Inklusivität einmal je vorbereitetem Dreieck statt einmal je Sample. Ihr gemessener Nutzen bleibt begrenzt und ist von den neuen Perspektivmessungen getrennt.
- Im aktuellen `AREMDL02`-Lauf beträgt das mediane Bio-Speedup gegenüber der nativen Baseline rund **2,0–2,2×**. Trotzdem überschreiten `animated4` und `arena6` weiterhin in allen 15 Messframes das 16,7-ms-Budget; dies ist **keine** 60-FPS-Zusage.

## Historischer orthografischer Vorher-/Nachhervergleich

**15 alternierende Paare, 256×256, Tile 32, 4 Worker.** Diese `AREMDL01`-Messungen stammen aus dem ursprünglichen Referenzarena-Changeset und sind nicht mit dem späteren Perspektivpfad zusammenzurechnen.

| Workload | Native Baseline median vorher → nachher | Bio median vorher → nachher | Bio p95 vorher → nachher | Bio max vorher → nachher | Bio-Speedup nachher (Medianverhältnis) | Slow-Frames nachher >16,7 ms |
|---|---:|---:|---:|---:|---:|---:|
| `animated4` (vier animierte Figuren) | 85,55 → 88,67 ms | 36,81 → 36,26 ms (−1,47 %) | 46,10 → 49,28 ms | 48,84 → 71,33 ms | 2,45× | 15/15 |
| `static2` (Baumstamm + Felsen) | 23,61 → 22,25 ms | 10,94 → 10,49 ms (−4,04 %) | 13,43 → 16,45 ms | 14,11 → 17,64 ms | 2,12× | 1/15 |
| `arena6` (4 Figuren + 2 Umfeldobjekte) | 106,34 → 101,44 ms | 42,33 → 41,28 ms (−2,48 %) | 47,50 → 57,34 ms | 47,61 → 61,73 ms | 2,46× | 15/15 |

Vorher und Nachher verwendeten denselben Host, dieselben sechs nach SHA-256 verifizierten Originale, dieselbe Geometrie, Konfiguration und Samplezeitpunkte. Für jeden Fall wurde die vollständige Framepufferparität mit der seriellen Referenz bestätigt. Die erhöhten p95-/Maximalwerte, besonders der 71,33-ms-Ausreißer in `animated4`, bleiben als Last-/Hostempfindlichkeit relevant.

## Aktueller AREMDL02-Perspektivbenchmark

**Ausgeführt am 2026-10-12, auf dem Sandbox-Host; 15 alternierende Baseline-/Bio-Paare, 3 Warmups, 256×256, Tile 32, 4 Worker, feste serialisierte Perspektivkamera.** Für jeden Case ist `full_buffer_parity=true`; das Receipt enthält 15 Framehashes. Alle sechs vom Nutzer bereitgestellten Arena-GLBs stimmen nach dem Lauf weiterhin mit den SHA-256-Werten im Modellmanifest überein; die Quellhashes blieben vor/nach dem Benchmark identisch.

| Workload | Eingabedreiecke | Baseline median / p95 / max | Bio median / p95 / max | Bio-Speedup (Medianverhältnis) | Bio-Frames >16,7 ms |
|---|---:|---:|---:|---:|---:|
| `animated4` | 68.775 | 60,226 / 62,148 / 63,038 ms | 27,619 / 29,098 / 29,748 ms | 2,181× | 15/15 |
| `static2` | 20.477 | 15,077 / 21,087 / 21,170 ms | 7,485 / 11,861 / 12,385 ms | 2,014× | 0/15 |
| `arena6` | 89.252 | 75,334 / 78,497 / 78,847 ms | 37,165 / 38,995 / 39,257 ms | 2,027× | 15/15 |

**Interpretation:** Der Perspektiv-/Clippingpfad besteht die exakte Pufferparität für alle drei Cases und zeigt in diesem Lauf etwa 2× Bio-Speedup. `static2` blieb unter dem Framebudget; sämtliche Frames in `animated4` und `arena6` lagen darüber. Das sind beobachtete Workload-Werte eines geteilten Hosts, weder geräteunabhängige FPS-Angaben noch statistische Konfidenzintervalle. Sie dürfen nicht direkt mit dem historischen orthografischen Lauf gleichgesetzt werden.

Das vollständige Receipt und die komprimierten RGBA-/Resolved-/Depth-Arrays liegen unter `evidence/reference-arena-perspective-20261012/`:

- `benchmark.json`
- `animated4-frames.npz`
- `static2-frames.npz`
- `arena6-frames.npz`

## Interpretation der Phasenmessung

In der historischen optimierten `arena6`-Messung betrug die mediane Raster-Workerarbeit 28,56 ms (Summe der gemessenen Workerintervalle), gegenüber rund 0,46 ms MSAA- und 2,55 ms AA-Workerarbeit. Workerarbeitszeiten summieren über parallele Arbeit und sind **keine Wandzeit**.

In einer Bio-Frontier-Welle können Raster, MSAA und AA abhängig von Tile-Abhängigkeiten überlappen. Die gemeinsamen `*_ms`-Wallfelder für diese Stufen dürfen daher weder addiert noch als isolierte Phasendauern interpretiert werden. Als Latenz dient `frame_total_ms`; als Rechenarbeitsanteil dienen die separat ausgewiesenen `*_worker_work_ms`-Summen.

## Referenzviewer und Funktionsgrenzen

`reference_arena/` ist eine rein visuelle Three.js-Ansicht mit WebGL, perspektivischer Kamera, GLB-Originaltexturen/-materialien, Animationen und Orbit-Steuerung. Sie ist ein visueller Referenzpfad, **kein dritter Timing-Backend**; ihr Browser-FPS-Zähler ist keine native Messung.

`AREMDL02` bringt Perspektivprojektion und Clipping in den nativen C++-Pfad. Native Textur-/UV-Interpolation und originale PBR-Materialzuweisungen sind weiterhin nicht integriert; die Beleuchtung ist diagnostisch pro Fläche. Browser- und native Ausgabe sind keine pixelgleichen Renderings. Der nächste Funktionsschritt ist der explizite Attribut-/Materialvertrag aus [`docs/native-perspective-texture-pbr-plan.md`](native-perspective-texture-pbr-plan.md), während `ARERIN01`, `AREMDL01`, VertexColor- und Diagnosepfad rückwärtskompatibel bleiben. Es gibt weiterhin keine unbelegte Grundlage für LOD-, Sichtbarkeits- oder Pixelarbeitsreduktionen.

## Reproduktion

1. Die vom Nutzer bereitgestellte ZIP lokal ablegen (Originalmodelle bleiben privat):

   ```sh
   python tools/install_reference_arena_assets.py /pfad/SoftwareGPU_Referenzarena_GLB_Modelle.zip
   ```

   Der Installer prüft Größe und SHA-256 der sechs ausgewählten GLBs gegen `evidence/original-model-manifest-v1.json`; `reference_arena/assets/*.glb` wird Git-ignoriert und **nicht** committet. Für den nativen Benchmark muss `--assets` auf ein Verzeichnis mit den Originaldateinamen aus dem Manifest zeigen.

2. Viewer aus dem Repositoryroot starten:

   ```sh
   python -m http.server 8000 --directory reference_arena
   ```

   Im Browser `http://localhost:8000/` öffnen (Three.js 0.180.0 und Addons werden von jsDelivr geladen).

3. Perspektivbenchmark der sechs Originalmodelle wiederholen:

   ```sh
   python tools/benchmark_models.py \
     --assets /pfad/zu/den/Originaldateien \
     --output-dir /tmp/reference-arena-perspective \
     --phase bench --projection perspective \
     --cases animated4,static2,arena6 --repeats 15 --seconds 600
   ```

4. Regressionstests ausführen:

   ```sh
   python -m unittest discover -s software_gpu/tests -p 'test_*.py' -v
   ```

5. Historische Orthogonal-Receipts und komprimierte Frames liegen unter `evidence/reference-arena-{before,after}-...-20261012.*`; der aktuelle Perspektivlauf liegt in `evidence/reference-arena-perspective-20261012/`. Die sechs GLB-Binaries sind nicht eingecheckt.

## Validierung des aktuellen Draft-PR-Commits

- **Vollständige Projektsuite auf Commit `814a293`:** `python -m unittest discover -s software_gpu/tests -p 'test_*.py' -v` → **286 bestanden, 2 übersprungen** (113,64 s).
- **Fokussierte AREMDL02-Tests vor dem Push:** 12 Modell-/Projektionsprüfungen bestanden; enthalten Clipping an sechs Ebenen, Culling und animierte Topologieänderung mit exakter Einworker-/Bio-Parität.
- **GitHub CI für den aktuellen PR-Head:** 11 Checks erfolgreich, 0 fehlgeschlagen, 0 ausstehend.
- **Perspektivbenchmark:** drei ausgewählte Cases, je 15 Framehashes und `full_buffer_parity=true`; Quellhashes stabil; sechs Original-GLB-Hashes am Ende manifestkonform.
- Python-/Viewer-JavaScript-Syntaxprüfung bestand; der Sandbox-Browser lud zuvor **6/6** Viewer-Modelle mit vier Animationsauswahlen.
- `git diff --check` bestand. Original-GLBs und Native-Buildartefakte bleiben außerhalb des Commits.

## Handoff / nächste sinnvolle Schritte

1. Draft-PR #48 reviewen; nicht aus diesen Messungen auf eine fertige 60-FPS-Spielepipeline schließen.
2. Den gleichen gepaarten Perspektivbenchmark auf einem weniger variablen oder dedizierten Runner wiederholen und p95/Maximum weiterhin neben dem Median bewerten.
3. Den nächsten Funktionsschritt gemäß `docs/native-perspective-texture-pbr-plan.md` implementieren: versionierter Importvertrag, perspektivisch korrekte UV-Interpolation und danach begrenzte Originaltextur-/PBR-Unterstützung. Alpha, Normalmaps, Sampler/Mips und Farbmanagement explizit spezifizieren.
4. Nach Textur-/Materialintegration denselben Arena-Input, dieselben Originalhashes und dieselbe Kamera erneut gegen serielle Referenz, native Baseline und Bio-Scheduler messen; Perspektiv-, Sampling-, Beleuchtungs- und Resolve-Kosten getrennt berichten.
