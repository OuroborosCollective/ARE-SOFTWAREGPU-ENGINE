# CI-, Test- und Coverage-Gates — ehrlicher Stand

Frage: „Wird wirklich jede mögliche Funktion getestet und jede mögliche
Fehlfunktion mit roten Gates erkannt?"

**Kurze, ehrliche Antwort: Nein — und „jede mögliche Fehlfunktion" ist
prinzipiell unmöglich.** Tests können nur spezifiziertes Verhalten gegen
konkrete Eingaben prüfen; die Eingabemenge eines Rasterizers ist praktisch
unendlich. Was man erreichen kann — und was dieser Stand tut — ist:

1. Jede **spezifizierte Vertragsbedingung** (fail-closed-Pfade, Fehlercodes,
   Byte-Identität, Budgets) hat einen Test, der bei Verletzung rot wird.
2. **Coverage-Floors** machen es unmöglich, dass Kernmodule still ihre
   Abdeckung verlieren, ohne dass die CI rot wird (`tools/coverage_gate.py`).
3. Was **bewusst nicht** getestet ist, ist hier aufgelistet und begründet.

## Was die CI tatsächlich ausführt

| Workflow | Lanes | Läuft auf PR | Läuft auf Push nach main |
|---|---|---|---|
| `cpu-regressions.yml` | Ubuntu/Windows × Python 3.11/3.12 (4), Wheel-/CLI-Smoke (1), LLVM-JIT × Ubuntu/Windows (2) | ja | ja |
| `external-cpu-evidence.yml` | Mesa llvmpipe × Worker 1/2/4/8 (4) | ja | nein |
| `aurion-offline-glb.yml` | CPU-GLB-Worker (4) | ja (pfadabhängig) | ja (pfadabhängig) |

Daraus folgt: ein PR sieht bis zu 15 Checks, ein Push auf main sieht 7–11.
Alle Gates auf dem main-Head `9516d73` sind grün (7/7 SUCCESS).

## Gemessene Abdeckung (CPU-Lane ohne numba, Suite: 150 Tests)

Gemessen mit `tools/coverage_gate.py` (stdlib `sys.monitoring`, Python ≥ 3.12).
Die Floors sind **Mindestwerte**, bei Unterschreitung schlägt der Gate fehl
(Test `test_coverage_gate.py` läuft als Teil der Suite, kein Workflow-Eingriff
nötig; Python-3.11-Lanes überspringen ihn, dort gilt die Suite selbst).

**Kanonische Gate-Lane:** Der Monitoring-Subprozess läuft auf der kanonischen
Lane **Linux + Python 3.12**. Grund: Teile des Codes sind plattformbedingt nur
unter Linux ausführbar (`import resource`, der RSS-Receipt-Block im Worker,
der Linux-only Memory-Budget-Test) — Windows/macOS messen strukturell ~3
Punkte weniger und würden kalibrierte Floors ohne echten Abdeckungsverlust
reißen. Auf allen anderen Lanes läuft weiterhin die **volle funktionale
Suite** (150 Tests) unmonitored; nur die Floor-Prüfung ist gepinnt. Die
schnelle Negativkontrolle des Gates läuft überall.

| Datei | Abdeckung | Floor |
|---|---|---|
| `graphics/framebuffer.py` | 100.0 % | 95 % |
| `graphics/rasterizer.py` | 100.0 % | 98 % |
| `graphics/postprocess.py` | 98.9 % | 95 % |
| `graphics/geometry.py` | 97.4 % | 94 % |
| `network/security.py` | 98.2 % | 88 % |
| `graphics/shader.py` | 94.3 % | 88 % |
| `graphics/tile_backend.py` | 92.6 % | 88 % |
| `integrations/aurion/offline_render_worker.py` | 79.7 % | 75 % |
| `main.py` (CLI) | 56.2 % | 35 % |
| **Gesamt (inkl. Demos/Benchmarks)** | **63.5 %** | **62 %** |

Die LLVM-JIT-Lane (numba installiert) deckt zusätzlich
`graphics/compiled_tile.py` ab; sie trägt hier keinen Floor, weil die CPU-Lane
ohne numba läuft.

## Was bewusst NICHT getestet ist — und warum

- **3 defensive Zeilen in `geometry.py` (Slow-Path)**: `wv < _MIN_W`-Break,
  Non-Finite-Screen-Break, `len(screen_v) != 3`-Continue. Nach
  Sutherland–Hodgman-Clipping gilt konstruktionsbedingt `w ≥ _MIN_W` und
  `|ndc| ≤ 1` (bis auf Float-Rundung) — die Zeilen sind durch reguläre
  Eingaben praktisch unerreichbar. Empirisch bestätigt: Sliver- und
  Riesen-Koordinaten-Probes treffen sie nicht. Sie bleiben als Defensiv-
  Absicherung stehen und sind vom Floor ausgenommen.
- **Demos und Beispielskripte** (`examples/`, `directx_demo`,
  `mmorpg_server_demo`, Benchmarks als Skripte): laufen als CI-Schritte
  (Exit-Code- und Smoke-Niveau), sind aber keine Unit-Test-Ziele.
- **`integrations/aurion/_offline_child.py` (0 % in-process)**: läuft per
  Design im Isolations-Subprozess; sein Verhalten wird über die Receipts des
  Workers (Hash-, Deadline-, Speicher-Gates) von außen bewiesen.
- **Integrations-Demos mit geringer Abdeckung**: `blender_render_engine.py`
  (55 %), `image_filter_endpoint.py` (44.5 %), `npc_fallback_audit.py`
  (20.9 % — der Großteil läuft über SHA-gepinnte GLB-Fixtures),
  `network/dispatcher.py` (23.3 %). Diese Pfade sind experimentelle
  Integrationen; ihre Sicherheitsgrenzen liegen in `network/security.py`
  (98.2 % abgedeckt).
- **Keine Aussage über „alle möglichen Fehlfunktionen"**: weder Fuzzing noch
  Property-Testing über den gesamten Eingaberaum. Die Byte-Identitäts-Gates
  und Orakel-Tests (verbatim-Originalimplementierung als Testorakel für
  `prepare_triangles`) decken spezifiziertes Verhalten ab, nicht jede
  denkbare Eingabe.

## Neue rote Gates dieses Slices

- `test_fail_closed_gaps.py` (33 Tests): Framebuffer-Export-Vertrag (BMP/PPM-
  Layout, Padding, Bottom-up-BGR, Determinismus), Depth-Test inkl.
  Tie-Break, Geometry-Fail-fast (TypeError bei Nicht-dict-Varyings,
  IndexError bei ragged/float Indices), Slow-Path-Sliver-Verwerfung,
  Tile-Backend-Early-Exits, Shader-Matrix-Mathematik, komplette
  Admission-Policy-Unit-Fläche (`security.py` inkl. render_mesh/physics/
  boids-Validierung und spezifischer Fehlercodes).
- `test_cli_contract.py` (6 Tests): `--help`-Vollständigkeit, argparse-Exit 2,
  `--info`-Telemetrie, `--blender` schreibt valide BMP, `--server` schlägt
  ohne Auth-Token fehl bevor ein Socket gebunden wird, Nicht-Loopback-Bind
  wird vor Token-Prüfung abgelehnt.
- `test_coverage_gate.py` (2 Tests): Floors halten (Subprozess-Lauf der
  Suite unter Monitoring, Rekursion per `COVERAGE_GATE_INNER=1`
  ausgeschlossen); Negativkontrolle — die Floor-Auswertung erkennt
  Verletzungen nachweisbar.

Lokal ausführen: `python tools/coverage_gate.py --verbose` (Python ≥ 3.12).
