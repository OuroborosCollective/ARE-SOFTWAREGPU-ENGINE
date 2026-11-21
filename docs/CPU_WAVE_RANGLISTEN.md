# SoftwareGPU: CPU-Ranglisten (beleggebunden)

**Datenstand:** SpherePop-Receipt 381f3a8d7053; Single-Origin 2cfd8be80d3b.

**Historischer Integrity-Status:** legacy-git-blob-pinned-self-digest-mismatch. Unveränderter Git-Blob statt stillschweigend umgeschriebener historischer SHA-256. Neue Messungen verlangen einen kanonischen SHA-256 sowie einen Abgleich aller Quellhashes mit dem exakten Checkout.

Nur reale CPU-Rohzeiten mit mindestens 15 Wiederholungen und verifizierter Bild-/Depth-Parität. Die Rangfolge gilt **nur innerhalb der jeweiligen Szene und Auflösung**. Keinerlei GPU-, Gameplay-FPS- oder Julia-Renderer-Parität ist daraus ableitbar.

## Neue Testreihen (neueste zuerst, getrennt von CPU-Leistungsrängen)

**Regel:** Neuere registrierte Testreihen stehen stets oben; gleiche Daten werden nach stabiler Test-ID sortiert. Registrierung ist **kein CI-Erfolg, FPS-Wert oder Benchmark-Sieg**. Erst originale SHA- gebundene CPU-Receipts und bestandene vollständige Frame-/Depth-Gates dürfen in eine vergleichbare Leistungsrangliste übernommen werden.

| Hinzugefügt | Testreihe | Projektfläche | Prüfstand | CPU-Zeit / FPS |
|:--|:--|:--|:--|:--|
| 2026-11-20 | glTF 2.1/GLB v3 Entwurf: unabhaengige Khronos-Assets, SHA-Replay (`software_gpu/tests/test_gltf21_glb3_independent_assets.py`) | test | **registriert; CI separat prüfen** | **nicht gemessen** |
| 2026-11-20 | glTF 2.1/GLB v3 Entwurf: Python/C++17-Fuzz-Negativtests (`software_gpu/tests/test_gltf21_glb3_fuzz.py`) | test | **registriert; CI separat prüfen** | **nicht gemessen** |
| 2026-11-20 | glTF 2.1/GLB v3 Entwurf (nicht ratifiziert): opt-in Sandbox-Vertrag (`software_gpu/tests/test_gltf21_glb3_sandbox.py`) | test | **registriert; CI separat prüfen** | **nicht gemessen** |
| 2026-11-20 | PyPI: Linux-/Windows-Installation und Registry-Integritaet (`software_gpu/tests/test_public_package_release.py`) | test | **registriert; CI separat prüfen** | **nicht gemessen** |
| 2026-11-19 | Neue Tests zuerst: Ranglistenvertrag (`software_gpu/tests/test_test_series_catalog.py`) | persistence | **registriert; CI separat prüfen** | **nicht gemessen** |
| 2026-11-19 | Code Ontology: Suche, Impact und Diff (`software_gpu/tests/test_code_ontology_ci.py`) | test | **registriert; CI separat prüfen** | **nicht gemessen** |
| 2026-11-19 | Visual Asset Lab: UV and material evidence (`software_gpu/tests/test_visual_asset_lab.py`) | test | **registriert; CI separat prüfen** | **nicht gemessen** |
| 2026-11-19 | Visual Asset Lab: GLB wireframe (`software_gpu/tests/test_visual_asset_lab.py`) | effects | **registriert; CI separat prüfen** | **nicht gemessen** |
| 2026-11-07 | GLB-BIN-Strukturdiagnose (`software_gpu/tests/test_glb_diagnostic_evidence.py`) | test | **registriert; CI separat prüfen** | **nicht gemessen** |
| 2026-10-20 | Historische CPU-Wellenreceipts (`software_gpu/tests/test_spherepop_rankings.py`) | test | **registriert; CI separat prüfen** | **nicht gemessen** |

## CAG/SpherePop/Doppler: ganzer Draw mit Welle

**x-Faktor:** Median der 15 gepaarten Tiles-/Backend-Zeiten. 1,00× = Gleichstand, unter 1,00× = Backend langsamer.

| Szene | Native C++ ms | Batch-first ms | Tiles ms | C++ ggü. Tiles | Batch ggü. Tiles | Rang 1 |
|:--|--:|--:|--:|--:|--:|:--|
| large-surfaces, 32 px (8 Dreiecke) | 1.178829 | 2.181734 | 3.739977 | 3.180× | 1.714× | native-cpp |
| procedural400, 32 px (400 Dreiecke) | 3.931035 | 13.204037 | 12.861730 | 3.253× | 0.976× | native-cpp |
| large-surfaces, 64 px (8 Dreiecke) | 2.276167 | 4.678524 | 11.527986 | 5.058× | 2.462× | native-cpp |
| procedural400, 64 px (400 Dreiecke) | 4.972207 | 20.397879 | 20.119249 | 4.047× | 0.987× | native-cpp |

## Single-Origin Impact Waves: drei unterschiedliche Wirkungen

| Auflösung | Ring ms | Sofort ms | Vollfenster ms | Rang 1 |
|:--|--:|--:|--:|:--|
| 32 px | 0.033493 | 0.041838 | 0.043351 | Ring |
| 64 px | 0.134993 | 0.166041 | 0.170339 | Ring |
| 128 px | 0.595413 | 0.725036 | 0.744091 | Ring |
| 256 px | 2.467414 | 3.010150 | 3.081933 | Ring |

**Semantik-Gate:** Ring verändert nur ein schmales Zeitfenster; daher nicht bildgleich mit Sofort/Vollfenster und **kein** gleicher-Output-Speedup. Nur Sofort vs. Vollfenster besitzen RGBA-Parität. Native C++ ist hier nicht mit Julia-Wellenmodellen als vollständiger Renderer vergleichbar.

**Nachweise:** [SpherePop-Rohreceipt](../evidence/spherepop-wave-ranked-cpu-20261020.json) · [Impact-Rohreceipt](../evidence/single-origin-time-window-20261020.json) · [Julia/C++-Differentialtest](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/39635587649).

Aktualisierte, **nicht automatisch nach main geschriebene** Live-Messungen stehen als Job-Zusammenfassung und herunterladbares Receipt im [CPU-Wave-Leaderboard-Workflow](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/workflows/cpu-wave-leaderboard.yml). Messungen von verschiedenen Runnern werden separat gehalten.
