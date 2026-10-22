# Band-Rasterizer: Konsolidierung von PR #154 / #155 / #156

## Entscheidung und Grenze

Gewinner ist die float32-Implementierung aus #155, mit `is_top_left` als
Modulimport und belastbaren Differentialtests statt des absoluten Zeitlimits.
Die Änderung betrifft ausschließlich den explizit gewählten historischen
`bands`-Backend. Der Standard bleibt `tiles`; C++-, JIT-, GPU- und
Aurion-Gameplay-Verhalten werden nicht aus diesen CPU-Messungen abgeleitet.

Geprüfte Basis: `048d794ba563f64af317cd216061d3a85d9cbafa`.

| PR | geprüfter Head | Ergebnis |
|---|---|---|
| #154 | `c938a4eb099c8b9afc7ebcba09a6d77e6370329c` | bytegleich; redundante Top-left-Implementierung, zusätzliche Array-Indizierung im Pixelpfad |
| #155 | `28f85a7bf2640c0d2e09b36ccb6c778d3bb462a8` | bytegleich; explizite float32-Skalare und kanonische Kantenregel; ausgewählt |
| #156 | `bf182361874bbfae529168e3a954a26978cc576a` | verworfen: NumPy-1.26-Skalarpromotion verletzt Farb-/Tiefenparität |

## Numerischer Nachweis

Der eingefrorene Referenzkern in `software_gpu/tests/fixtures/band_reference.py`
ist die unveränderte `_rasterize_band`-Funktion der genannten Basis. Er bleibt
bewusst unoptimiert. Beide Pfade verwenden die unveränderte kanonische
Geometrievorbereitung; deren Quellhash ist im Receipt enthalten.

22 Szenen × drei Auflösungs-/Worker-Konfigurationen ergeben 66 vollständige
RGBA8-/float32-Tiefenbuffervergleiche je Variante und NumPy-Version. Enthalten:
perspektivische Interpolation, seeded Clipping, Pixelzentren und Subpixel,
gemeinsame Kanten, Sliver, Degeneration, Viewport-Grenzen, 1×1-Buffer,
Tiefenreihenfolge/Gleichstand, flaches Alpha und nichtfinite Primitive.
Ein zusätzlicher analytischer Test rendert die beiden Dreiecke eines Quads
getrennt und beweist lückenlose, überschneidungsfreie Abdeckung von 1024 Samples.

- NumPy **2.3.5**: alle drei Originalvarianten und Kandidat 66/66 bytegleich.
- NumPy **1.26.4**: #154, #155 und Kandidat 66/66 bytegleich; #156 weicht
  in **50/66** Fällen ab, insgesamt **7240 Tiefenwerte und 2998 Farbbytes**.
- Beispiel #156: Perspektivszene 32×32, ein Worker: 99 abweichende Tiefenwerte.

Die Python-float-Konvertierung in #156 führt unter NumPy 1.x zu anderer
Zwischenpräzision. Unter NumPy 2.x können schwache Python-Skalare wieder in
float32 eingehen; ein grüner Lauf allein auf 2.x übersieht deshalb den Fehler.
Die neue CI-Lane hält NumPy 1.26 explizit fest; die bestehende Matrix prüft den
aktuellen zulässigen NumPy-Stand.

Wolfram Language wurde unabhängig ausgewertet:

```wl
{Expand[((px-ax)*(by-ay)-(py-ay)*(bx-ax))-
        ((px-ax)*(by-ay)+(py-ay)*(ax-bx))],
 FullSimplify[Equivalent[dy>0 || (dy==0 && dx<0),
                         dy>0 || (dy==0 && -dx>0)],
              Element[{dx,dy},Reals]]}
(* {0, True} *)
```

Dies bestätigt die exakte Algebra und Kantenkonvention, ausdrücklich keine
IEEE-float32-Byteparität. Diese stammt ausschließlich aus realen Renderläufen.
Bounding-Box-Rundung, halb-offene Bandgrenzen, strikt kleinere Tiefe und
Interpolationsreihenfolge bleiben unverändert.

## Warum der ursprüngliche #155-Zeittest ersetzt wurde

Der alte Test rendert 150-mal Z=0-Geometrie ohne Buffer-Clear. Nur der erste
Durchlauf schattiert; danach verwirft Early-Z gleiche Tiefe. Ein Median unter
2000 ms ohne Baseline ist kein Speedup-Nachweis und schwankt mit dem Host.
Er wird durch deterministische Bild-/Tiefenregressionen und einen separaten
realen Gesamt-Draw-Benchmark ersetzt. Kein bestehender main-Test wird entfernt.

## Reproduktion und Evidence

```sh
python -m unittest software_gpu.tests.test_band_inline_parity -v
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  taskset -c 0 python -m software_gpu.benchmarks.compare_band_candidates \
  --output evidence/band-inline-review/paired-numpy2.json --repeats 15
```

Für andere Hosts einen erlaubten CPU-Kern wählen; `taskset` ist Linux-spezifisch.
Für historische Varianten müssen die oben gepinnten Git-Objekte vorhanden sein.
Der Benchmark führt ausschließlich diese lokalen, geprüften Python-Quellen aus.
NumPy 1.26 separat in einer isolierten Umgebung mit `--differential-only` prüfen.

15 Runden mit wechselnder Reihenfolge, ein Warmup je Variante/Szene,
ein Worker und ein CPU-Affinity-Kern. Jeder vollständige `draw_mesh` enthält
Geometrievorbereitung, Rasterung und echte Fragmentshader. Buffer-Clear liegt
außerhalb der Zeitmessung, findet aber vor jedem Draw statt. Alle gemessenen
Draws werden byteweise geprüft. Rohzeiten, Median/IQR/MAD, gepaarte Ratios,
Quell-/Buffer-SHA256, Python/NumPy/CPU/Affinity und Thread-Umgebung stehen in den
JSON-Receipts. `dirty=true` benennt den getesteten Arbeitsbaum ehrlich; die
Quellhashes binden die tatsächlich ausgeführte Version statt nur den Parent-SHA.
Die historischen #156-Zeiten unter 2.x sind keine Freigabe für 1.x.

## Flächen, Risiken und Rücknahme

- Core/Produktion: `software_gpu/graphics/rasterizer.py`, nur `bands`-Pixelpfad.
- Tests/Evidence: eingefrorenes Orakel, Differentialtests, gepaarter Benchmark.
- Persistenz: versionierte JSON-Receipts und genau ein neuer Memory-Eintrag.
- Effekte: zusätzlicher NumPy-1.26-CI-Job; keine Dienste oder Deployment.
- Runtime-Projektion: reale lokale CPU-Draws, kein Beleg für Aurion oder Hardware-GPU.

Hauptrisiko ist eine spätere Änderung der float32-Auswertungsreihenfolge. Beide
NumPy-Generationen und die eingefrorene Referenz schützen davor. Leistungswerte
sind deskriptive Messungen dieser Szenen auf diesem Host, keine universelle
Beschleunigung und kein belastbarer Unterschied im niedrigen Prozentbereich.
Rücknahme: Gewinner-Merge revertieren; kein Datenformat und keine Migration.

Abschluss setzt grüne CI auf dem finalen Head und unabhängigen main-Readback
voraus; lokale Tests allein erlauben keine Behauptung über diese CI-Zustände.

## Finale gepaarte Band-Messreihe

| Szene | main ms | Kandidat ms | gepaarter Faktor | #154 | #155 original |
|---|---:|---:|---:|---:|---:|
| 128 px / 160 Dreiecke | 85.401 | 53.662 | 1.548× | 1.458× | 1.541× |
| 128 px / 8 Dreiecke | 549.213 | 339.792 | 1.619× | 1.608× | 1.709× |
| 256 px / 320 Dreiecke | 464.936 | 315.065 | 1.503× | 1.496× | 1.539× |

CPU: AMD EPYC 9V74 80-Core Processor; Python 3.12.14, NumPy 2.3.5; Affinity [0].
Der Faktor ist der Median der 15 individuellen main/Kandidat-Paare, nicht der Quotient der Tabellenmediane.

Lokale Gesamtsuite: 476 Tests, 10 deklarierte Skips; ein Hostfehler bei
`test_android_unix_domain_socket_ipc` (AF_UNIX EPERM) und ein davon abgeleiteter
Coverage-Gate-Fehler. Der innere Coverage-Lauf meldet ebenfalls ausschließlich
diesen Socketfehler (476 Tests/11 Skips). Vollständige unveränderte Logs und
Quellbindung: `evidence/band-inline-review/local-suite.json`, `stdout.log.gz`,
`stderr.log.gz`. Kein Coverage-PASS wird daraus behauptet. Der Benchmark wurde
nach Ergänzung seiner Fixture-Quellhashes erneut ausgeführt; der lokale
Suite-Receipt dokumentiert die davor geprüfte Benchmark-Dateiversion.

## Bereits bestehende NumPy-1.26-Backend-Grenze

Der zusätzlich versuchte alte Raster-Vertragstest zwischen `bands` und `tiles`
zeigt unter NumPy 1.26.4 2169 unterschiedliche Tiefenwerte bei gleichen Farben
in der 128×128-Perspektivszene. Das ist auf unverändertem main, originalem #155
und dem Kandidaten exakt gleich reproduzierbar
(`numpy126-existing-tile-drift.json`). Es handelt sich nicht um eine durch
Inlining eingeführte Regression. Der fehlgeschlagene Zusatzlauf bleibt in
`numpy126-tests.log` erhalten. Die neue Legacy-CI-Lane prüft deshalb ausdrücklich
den Gegenstand dieses PRs: eingefrorene alte gegen neue Band-Ausführung und
analytische gemeinsame Kanten (`numpy126-band-tests.log`: 2 Tests PASS).
Bestehende Backend-Tests und Coverage-Grenzen bleiben unverändert in der vollen
CI-Matrix; der Befund wird nicht als allgemeine Backend-Parität verkauft.

Zusätzlicher Workbench-Lauf: 256 px, fünf Szenen, acht Modi, 15 Wiederholungen
(600 gemessene Draws plus Warmups), byteidentisch. Audit inklusive aller
deklarierten Checkout-Quellhashes PASS; Timing-Konsistenzprüfung durch die
Workbench-App ebenfalls CONSISTENT_TIMINGS. Vollständiger komprimierter Receipt:
`surface-plan-benchmark.json.gz`, unkomprimierter SHA-256
`4429f0ca60220d90f9cc33715934b66458cce89551d2a569e12a922a0da917bb`.
Dieser Nachbarpfad-Test belegt keinen zusätzlichen Band-Speedup.
