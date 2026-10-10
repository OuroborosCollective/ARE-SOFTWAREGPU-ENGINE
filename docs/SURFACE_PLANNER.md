# Mehrschichtiger Flächenplaner: CPU-Prototyp

`tiles-plan` ist ein ausdrücklich wählbarer Rasterpfad. Standard bleibt
`tiles`. Der Planer verwendet feste, deterministische Regeln und erzeugt
einen begrenzten vierfarbigen Graph-Nachweis der tatsächlich gewählten Arbeit.
Er ist kein allgemeiner Shader-Compiler und kein Nachweis von Gaming-GPU-Parität.

## Ausführen

```python
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.surface_plan import BATCH_FIRST_POLICY

renderer = SoftwareRasterizer(framebuffer, backend="tiles-plan", num_threads=1,
                              plan_policy=BATCH_FIRST_POLICY)
try:
    renderer.draw_mesh(vertices, indices, VertexColorShader())
    receipt = renderer.last_plan_receipt
finally:
    renderer.executor.shutdown(wait=True)
```

Der bestehende isolierte Offline-Worker akzeptiert ebenfalls
`render.backend = "tiles-plan"`. Sein Ergebnis enthält dann `surface_plan`.
Die Autorität bleibt `offline-read-only`; das ist keine Aurion-Liveintegration.
Für seinen bekannten `VertexColorShader` verwendet dieser Worker das Profil
`batch-first-v1`: Batch ab acht sichtbaren Samples, kein Eckscan und der
bestehende 64-Bbox-Samples/Dreieck-Fallback. Er schützt kleine Arbeit;
er ist kein neu kalibriertes universelles Kostenmodell.
Der generische Renderer ohne Profil verwendet weiterhin
`corner-scan-v1` mit den unten beschriebenen Regeln. Profile sind eingefroren
und pro Renderer gespeichert; parallele Ablationen ändern keine Modulkonstanten.

```bash
python -m software_gpu.benchmarks.compare_surface_plans --output-dir surface-plan-results --repeats 15 --pixels 256 --workers 1 --ablation --max-seconds 1800
python -m unittest software_gpu.tests.test_surface_plan -v
```

Der Benchmark schreibt echte CPU-Messungen, vollständige Plan-Receipts und
eine lokale HTML-Ansicht mit aufklappbaren farbigen Flächen. Er vergleicht
`tiles`, geplante skalare Shader und geplante Batch-Shader. Alle Ausgaben
einschließlich Float32-Tiefen werden in jedem Lauf byteweise verglichen.
Planung und Receipt-Erstellung liegen innerhalb der gemessenen Draw-Zeit.
Die vier Ablationen erzwingen Planung und trennen Scan an/aus von Batch an/aus.
Ein achter Modus `batch-first` misst zusätzlich das tatsächlich aktivierte
Profil einschließlich seines bestehenden Draw-Fallbacks.
Der Standardlauf behält seine drei Modi. Alle Wiederholungen werden interleaved
gemessen, mit Median, IQR, unskaliertem MAD, Rohsamples und gepaarten Verhältnissen.
CPU, Compiler, NumPy-Build, Thread-Umgebung und Seeds gehören zum JSON.
Zehn Quellhashes binden Benchmark, Fixture, Szenengenerator und Rasterkern.
Der positive Zeitdeckel wird in einem überwachten Unterprozess durchgesetzt;
bei Abbruch werden keine neuen Teilberichte veröffentlicht. `0` deaktiviert
den Deckel ausdrücklich. NaN/Inf sind ungültig. Grenzen: 1–30 Wiederholungen,
32–1024 px und 1–16 Worker; unter 15 Wiederholungen erscheint eine Warnung.

## Laufende Regeln und Kostenmodell

1. Bei durchschnittlich weniger als 64 Bounding-Box-Samples pro vorbereitetem
   Dreieck bleibt der Draw auf dem Referenzpfad. Diese feste Schätzung ist
   keine garantierte Laufzeitprognose. Ein kleiner Draw-Nachweis entsteht
   trotzdem; seine Zeit kann bei winzigen Jobs messbar sein.
2. Nur Bereiche mit mindestens 64 Samples werden an zwölf Kanten-Eckwerten
   klassifiziert. Die Rechnung verwendet dieselben Float32-Ausdrücke,
   dieselbe Operationsreihenfolge und dieselbe Top-left-Regel wie der dichte
   Pfad. Nichtfinite Zwischenwerte erzwingen dichte Prüfung.
3. Vollständig ausgeschlossene Bereiche überspringen Coverage, Tiefe,
   Interpolation und Shader. Vollständig enthaltene Bereiche sparen die
   Coverage-Vergleiche; Kantenwerte werden für Tiefe und Interpolation
   weiterhin berechnet. Grenzbereiche behalten die dichte Prüfung.
4. Ab acht sichtbaren Samples wird ein ausdrücklich deklarierter Batch-Shader
   genutzt. Kleinere Mengen und unbekannte Shader bleiben skalar.

Ein Batch-Anbieter deklariert `batch_fragment_equivalent_to` als seine
skalare Funktion und implementiert `fragment_shader_batch(varyings)`.
Ein Override der skalaren Funktion ohne passende Neudeklaration erzwingt
skalare Ausführung. Die Deklaration ist ein Anbieter-Vertrag, kein automatisch
erzeugter Äquivalenzbeweis. Für `VertexColorShader` ist die identische
Elementarithmetik durch reale Render- und direkte Konvertierungstests gepinnt.
Dieser Äquivalenzvertrag gilt für finite RGB-Tripel; nichtfinite Batch-Eingaben
werden abgewiesen und gehören nicht zum vereinbarten Eingabebereich.
Batch-Ausgaben müssen Integer-Arrays der Form `(N, 4)` mit Werten 0–255 sein.
Ungültige Ausgaben und Provider-Ausnahmen propagieren vor den Schreibzugriffen
des jeweiligen Batches; der gesamte Draw ist kein atomarer Transaktionspuffer.
Bereits abgeschlossene Kacheln bleiben bei einem späteren Fehler beschrieben.

Tiefe verwendet weiterhin strikt `<`; Einreichungsreihenfolge und
perspektivische Varying-Rechnung bleiben erhalten. Der geplante Pfad unterstützt
zusätzlich 0-D- und Matrix-/Tensor-Varyings durch eine eigene Sample-Achse.
Er wird nicht mit `tiles-jit` oder MSAA kombiniert.

## Vier Ansichten und tatsächliche Evidenz

| Fläche | Quellfläche | Inhalt und Grenze |
| --- | --- | --- |
| Blau / Core | `graphics/surface_plan.py` | Feste affine Klassifikationsregel; kein beliebiger nichtlinearer Shader-Beweis |
| Violett / Produktion | `graphics/tile_backend.py` | Wirklich bearbeitete Kachelkoordinaten, disjunkte Bufferregionen |
| Orange / Runtime-Projektion | `last_plan_receipt` | Tatsächlich gezählte Dense-/Corner-Auswertungen, ausgeschlossene Samples und Shader-Aufrufe |
| Grün / Test-Vertrag | `tests/test_surface_plan.py` | Anforderungen und separate Bild-/Tiefenparität; grüne Farbe allein beweist keinen Testlauf |
| Persistenz | Offline-Receipt / Benchmark-JSON | Abgeleitete Artefakte mit SHA-256, keine kanonischen Weltzustände |
| Effekt | Framebuffer | Lokale Farb-/Tiefenschreibzugriffe; keine Netzwerk- oder Gameplay-Effekte |

Der Graph enthält höchstens 128 Kachelzusammenfassungen mit je vier Knoten.
Alle Operationen werden gezählt; nur die detaillierten Knoten sind begrenzt.
Beim Referenz-Fallback sind `counts = null`, weil kein zusätzlicher Zähler
im Referenz-Hotpath aktiviert wird. Vier Draw-Knoten erläutern dann den Fallback.
Die additive Schema-Revision 2 enthält `binned_pairs`, `small_pairs`, das
tatsächlich verwendete Profil und maschinenlesbare `counter_units`. Die beiden
Pair-Merkmale werden vor Ausführung in konstantem Aufwand pro Dreiecks-Bbox
gezählt und stehen auch im Fallback zur Verfügung. Ausführungscounter fehlen
dort weiterhin. Bei geplanter Ausführung gilt:

```text
binned_pairs = inside + outside + boundary + scan_bypassed
small_pairs = scan_bypassed
shaded_samples = batch_fragment_samples + scalar_fragment_calls
```

`scalar_fragment_calls` zählt reale Shader-Aufrufe (hier einer pro Sample),
`batch_fragment_calls` reale Batch-Aufrufe, `batch_fragment_samples` deren
Sample-Anzahl. `shaded_samples` zählt Shader-Arbeit einschließlich Overdraw,
nicht die Anzahl einzigartiger Bildpixel. Neue Receipt-Felder verändern den
Plan-Digest; der Protokollname bleibt `are.surface-plan.v1`.
Worker-Reihenfolge beeinflusst den Plan-Digest nicht. Dieser Digest identifiziert
den Plan-Nachweis, nicht Mesh, Programmversion, Host oder vollständiges Bild;
diese Provenienz gehört in das umgebende Worker-/Benchmark-Receipt.

## Wolfram/CAG und Forschung

Die Datei `software_gpu/evidence/wolfram-surface-plan.v1.json` stammt aus
einer echten Wolfram-Language-Auswertung; das ausführbare Skript steht daneben
als `wolfram-surface-plan.v1.wl`. Affine Ecke-Identität und Summe der
Gewichte wurden symbolisch geprüft; das exakte 32×32-/8×8-Beispiel hat 210
enthaltene Pixel und 384 statt 1.024 Formelauswertungen. Die Tests lesen es
unabhängig mit Python `Fraction` zurück. Der Nachweis betrifft reale affine
Funktionen; konkrete Float32-Implementierung und Pixelrandregeln werden
zusätzlich gegen dichte Berechnung und reale Rasterausgaben getestet.

Die Runtime importiert keine Wolfram-Bibliothek und ruft keine CAG-HTTP-API
auf. Das ist die vorbereitende Wolfram-Orakel-Anbindung des begrenzten
Prototyps. Neue CAG-Regeln werden nicht automatisch geladen oder ausgeführt.

- Mirage, μGraphs auf mehreren Ausführungsebenen: https://arxiv.org/abs/2405.05751v3
- EqiForge, gemeinsame Tensor-/Tile-Umformungen: https://arxiv.org/abs/2609.12330v1
- Wolfram Computation API: https://www.wolfram.com/apis/documentation/cag/wolfram-language-computation-api/

Diese Arbeiten motivieren die Architektur. Ihre Hardware-GPU-/Tensor-Ergebnisse
sind keine Messwerte unseres CPU-Rasterizers. Für beliebige Shader, dynamische
Umformungsgraphen, Texturen/Beleuchtung und Hardwarevergleiche fehlt hier ein
Implementierungs- und Laufzeitnachweis. Amplitude, Connhex und Quicknode sind
für diesen lokalen Prototyp nicht erforderlich und werden nicht aufgerufen.

## Regressionsumfang

Die Suite prüft tatsächliche Farbbuffer und Tiefenbytes, 300 deterministische
Float32-Klassifikationsfälle, Clipping, Perspektive, Top-left, Depth-Ties,
Alpha-Speicherung, skalare Seiteneffekte, Override-Fallback, Tensor-Varyings,
Batch-Fehler, deterministische Worker, begrenzte Trace-Größe und einen echten
isolierten Offline-Job samt Receipt-Readback. Neue Kernmodule tragen jeweils
einen 95-%-Zeilen-Floor im vorhandenen Coverage-Gate. Branch-/Funktionsabdeckung
wird von diesem Projekt-Gate nicht ausgewiesen.
Zusätzliche Regressionen prüfen 500 unabhängig enumerierte Pair-Rechtecke,
echte Shader-Aufrufzähler, konkurrierende Profile, beide Ablationsrichtungen,
Zeitdeckel und negative Artifact-/Quellhash-Prüfungen. Der Benchmark selbst
hat jetzt einen 85-%-Zeilen-Floor im kanonischen Linux-Gate.

## Wiederverwendbare Workbench

[Plugin-Quellen und Bedienung](../plugins/softwaregpu-workbench/README.md)
bündeln Inventar, reale Regressionen, begrenzte Benchmarks, Receipt-Audit,
Ablationsanalyse, Kalibrierungshinweise und den vorhandenen CPU-Trainings-Preflight.
Ein Audit prüft gespeicherte Daten; es ersetzt keinen Rerender oder Head-CI.

## Lokaler Messstand vom 10. Oktober 2026

Ein Worker, fünf Repeats nach Warmup, rotierende Modus-Reihenfolge, identische
Szene und Quellcode-Prüfsummen pro Lauf. Die Referenz verwendet den bestehenden
`FlatShader`. Zahlen sind Mediane; die Rohsamples und Coverage-Nachweise stehen
in `evidence/surface-plan-validation-2026-10-10.json`.

| Szene | 128 px: Tiles / Plan-Batch ms | Faktor | 256 px: Tiles / Plan-Batch ms | Faktor |
| --- | --- | --- | --- | --- |
| Ein winziges Dreieck | 0,277 / 0,310 | 0,89× | 0,392 / 0,366 | 1,07× |
| 160 kleine Dreiecke | 41,069 / 29,333 | 1,40× | 84,852 / 37,435 | 2,27× |
| Große Flächen | 111,552 / 15,640 | 7,13× | 433,495 / 49,666 | 8,73× |
| Prozedural, 400 Dreiecke | 50,140 / 57,618 | 0,87× | 170,334 / 99,985 | 1,70× |
| Prozedural, 5.120 Dreiecke | 383,150 / 384,439 | 1,00× | 736,337 / 715,776 | 1,03× |

Faktoren unter 1 bedeuten eine Verschlechterung. Alle zehn Szenen-/Auflösungs-
Vergleiche liefern in allen Durchläufen byteidentische Farb- und Tiefenpuffer.
Winzige Dreiecke und die 128-px-5k-Szene nutzen den Referenz-Fallback; ihre kleinen
Differenzen erlauben keine Beschleunigungszusage. Die 400er-Szene ist bei 128 px
schlechter, bei 256 px besser. Der skalare Plan-Pfad ist überwiegend langsamer;
die Eckklassifikation allein ist hier kein robuster Leistungsgewinn.
Die großen Gewinne kommen hauptsächlich vom ausdrücklich deklarierten
Batch-Farbshader, nicht von den Graph-Farben oder einem allgemeinen Wolfram-
Compiler. Es gibt daher keine Änderung des Standards und kein allgemeines
Aktivierungsgate.

Lokal: 170 ausführbare Tests PASS, beide neuen Kernmodule 100 % Zeilenabdeckung,
Gesamtabdeckung 64,25 % und alle bestehenden/neuen Floors PASS. Der Host verbietet
AF_UNIX-Sockets; der bestehende Android-Unix-Socket-Test und sein vollständiger
Coverage-Unterlauf sind hier ausgenommen. Die kanonische vollständige Linux-/
Windows-/JIT-/Mesa-CI muss den vorgeschlagenen Commit separat prüfen.

## Batch-Profil und Kalibrierung, Oktober 2026

Der finale Lauf misst acht Modi bei 128 und 256 px, je 15 Repeats plus Warmup,
einen Worker und rotierende Reihenfolge auf AMD EPYC 9V74. Alle 1.280 Draws
liefern je Szene identische Farb- und Tiefenbytes. Der achte Modus misst genau
`batch-first-v1` mit seinem bestehenden Draw-Fallback. Die vier erzwungenen
Ablationen behalten den Fallback ausgeschaltet.

| Szene | 128 px: Batch-Profil / Tiles, gepaart | Entscheidung | 256 px: gepaart | Entscheidung |
| --- | ---: | --- | ---: | --- |
| tiny | 0.76× | tiles-reference | 1.11× | planned |
| small-triangles | 1.48× | planned | 2.87× | planned |
| large-surfaces | 8.25× | planned | 11.52× | planned |
| procedural400 | 1.38× | planned | 2.33× | planned |
| procedural5k | 1.00× | tiles-reference | 1.22× | planned |

Die 128-px-5k-Szene und winzige Arbeit behalten den Referenz-Fallback.
Die 5k-Fallback-Differenz ist kein Beschleunigungsnachweis. Der winzige
128-px-Draw ist hier langsamer (0,76×); sein Receipt-Mehraufwand ist im
Sub-Millisekunden-Bereich relevant. Für solche Jobs bleibt `tiles` geeignet.
Scan auf Batch liegt in den vier größeren Szenen unter 1; Batch-Bündelung ist
der gemessene Hebel. Dies ist kein universell kalibriertes Kostenmodell.
[Nachweisprojektion](../evidence/surface-plan-calibration-v2.json) enthält
Rohsamples, Median/IQR/MAD, gepaarte Kennzahlen, Counter und vollständige
Quellhashes sowie SHA-256 der vollständigen Graph-Artefakte.
Die ursprünglichen Messungen oben bleiben als historischer Stand erhalten.

Final lokal: 191 ausführbare Tests PASS; Oberfläche 100 %, Tile 98,88 %,
Benchmark 91,96 %, Gesamt 65,56 %. Alle Floors PASS. Die beiden oben
genannten AF_UNIX-/Coverage-Ausnahmen bleiben explizit; vollständige
kanonische Head-CI ist vor dem Merge erforderlich.
