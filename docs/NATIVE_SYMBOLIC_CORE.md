# Nativer symbolischer Berechnungskern

Der symbolische Testzweig enthält jetzt einen eigenständig kompilierten C++17-Kern.
Im laufenden Prozess werden keine Python-Module geladen und keine Python-Callbacks
aufgerufen. Wolfram liest die begrenzte Aufgabensprache vorab; der vorhandene
Python-Code dient zur einmaligen IR-Prüfung/Codeerzeugung sowie als unabhängige
numerische Testreferenz. Der bisherige NumPy-Forschungsprototyp bleibt als Referenz.

Der zusätzliche [geprüfte Direktpfad](NATIVE_DIRECT_INPUTS.md) reduziert nun
Eingabeübernahme und Validierungsdurchläufe; die ursprünglichen Messungen unten
bleiben als historische Ausgangsbasis erhalten.

## Ausführung

`native/symbolic/core.hpp` verwaltet Eingaben, Abhängigkeiten, Ergebniszustände und
alle wiederverwendbaren Puffer. `native/symbolic/main.cpp` ist der eigenständige
Frame-Runner. `software_gpu/research/native_symbolic.py` erzeugt aus dem validierten
Wolfram-IR eine feste `generated.hpp` und kompiliert sie zusammen mit dem Runner.
Der erzeugte Prozess benötigt die üblichen C/C++-Systembibliotheken, weder Python
noch Wolfram. Seine Graphstruktur und Formen stehen beim Kompilieren fest.

| Pfad | Arbeit je Frame | Datenbesitz |
| --- | --- | --- |
| `run fused` | Alle elementweisen Operatoren in einem gemeinsamen Durchlauf pro Form; lokale Float32-Zwischenwerte statt Tensorstapel | Geprüfte Eingaben und Ausgaben gehören dem C++-Kern |
| `run direct` | Eingaben und Zwischenwerte im Rechendurchlauf prüfen; vollständige Neuberechnung, kein Änderungsvergleich | Eingaben synchron geliehen, nur Ausgabepuffer im Kern |
| `run incremental` | Exakter Eingabevergleich und Neuberechnung nur abhängiger geänderter Knoten | Unveränderte Knoten werden wiederverwendet |
| Benchmark `fused-kernel` | Rechenkern auf zuvor geprüften Eingaben mit vorab reservierten Ausgaben | Nur ein gesonderter Messpfad, keine ungeprüfte Frame-Freigabe |

Der Modus wird beim Erstellen einer Engine festgelegt. In `fused` und `incremental` werden Änderungen über
vollständige Bitvergleiche erkannt; damit bleiben `+0` und `-0` unterscheidbar.
Nur neue/geänderte Eingaben werden erneut auf Endlichkeit geprüft, zusammen mit
dem Kopieren in den Staging-Puffer. Bereits identische Eingaben sind zuvor geprüft.
Abhängigkeiten werden in topologischer Reihenfolge ausgewertet. Ein Fehler
übernimmt weder Eingaben noch Teilergebnisse in den letzten gültigen Zustand.

Die öffentlichen Ergebnisreferenzen sind unveränderlich und gelten bis zum
nächsten erfolgreichen Frame. Der Kern reserviert beim Aufbau die Puffer; der
normale `evaluate`-Pfad allokiert keine Tensoren und führt keine Hashberechnung aus.
Der Graph-Hash bindet das Programm an seinen vorbereiteten Auftrag. Die Shapes
und mehrdimensionalen Koordinaten werden vorab geprüft; die numerischen Arrays
sind flach in C-Reihenfolge angeordnet.

## Numerischer Vertrag

Erlaubt sind `input`, `add`, `sub`, `mul` in IEEE-Binary32 und dieselben begrenzten
Graphen wie in `symbolic_wave.py`. Jede Operation behält ihre ursprünglichen
Operanden und Rundungsgrenzen. Reassoziation und FMA-Kontraktion sind deaktiviert.
Die fest vorgegebenen Compiler-Flags lauten:

```
-std=c++17 -O3 -fno-fast-math -ffp-contract=off -Wall -Wextra
```

Ein Fast-Math-Build wird zusätzlich vom Header abgewiesen. Zur Laufzeit wird
Rundung auf den nächsten Wert verlangt; auf den getesteten SSE-Systemen werden
Flush-to-zero/Denormals-are-zero abgewiesen. Nichtendliche Eingaben und auch
nichtendliche Zwischenergebnisse werden abgewiesen. Die Endlichkeitsprüfung
verwendet IEEE-Exponentbits und eine ganzzahlige Oder-Reduktion, damit der Compiler
sie ohne Änderung der Float32-Reihenfolge vektorisieren kann.

GCC beschreibt `-ffp-contract=off` als Abschaltung der Kontraktion:
https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html

## Bauen und ohne Python ausführen

Einmalige Vorbereitung im Repository mit NumPy und GCC/Clang:

```bash
python -m software_gpu.research.native_symbolic \
  --ir software_gpu/tests/fixtures/symbolic-edge.ir.json \
  --output-dir build/native-edge
```

Anschließend unabhängig von Python/Wolfram:

```bash
./build/native-edge/kernel info
./build/native-edge/kernel run fused < frames.bin
./build/native-edge/kernel run incremental < frames.bin
```

Oder die bereits erzeugten Quellen direkt neu bauen:

```bash
cd build/native-edge
g++ -std=c++17 -O3 -fno-fast-math -ffp-contract=off -Wall -Wextra main.cpp -o kernel
```

Unter Windows heißt die Datei `kernel.exe`; der Runner stellt stdin ausdrücklich
auf Binärbetrieb um. Die Build-Quellen, Flags, Compiler-Version und Binärdatei
werden im `build.json` per SHA-256 gebunden. Es gibt keinen stillen Python-Fallback.
Das Build-Werkzeug benötigt einen Repository-Checkout, da die nativen Quellen
nicht als Bestandteil des bestehenden Python-Wheels verteilt werden.

Das begrenzte Drahtformat enthält nacheinander: 8 ASCII-Bytes `AREF32V1`, Anzahl
Frames als uint32 little-endian, Eingabezellen je Frame als uint32 little-endian,
32 rohe Bytes des Graph-SHA-256, danach die Float32-Bits little-endian. Eingaben
stehen in `plan.inputs` (nach Namen sortiert), jede in C-Reihenfolge. 1–32 Frames
und insgesamt höchstens 8.388.608 Eingabezellen sind erlaubt. Unpassender Graph,
unpassende Länge, zusätzliche Bytes oder Überschreitung werden abgewiesen.
Ausgaben sind JSON mit uint32-Ergebnisbits in `plan.outputs`-Reihenfolge.
Ein numerisch ungültiger Frame erhält `ERROR`; nachfolgende Frames können weiter
laufen. Ein Protokollfehler beendet den Prozess mit Exit 2.

## Tests und Messgrenzen

```bash
python -m unittest software_gpu.tests.test_native_symbolic -v
python tools/benchmark_native_symbolic.py --output-dir native-results --repeats 15
```

Die Regressionen kompilieren und starten echte Programme. Sie prüfen Zufallsdaten
gegen die tatsächliche Renderer-Edge-Funktion, lokale Änderungen, die feste
32-Räume-Reduktion, mehrere Formen/Ausgaben, Input-only-Graphen, Signed Zero,
Subnormalzahlen, Rundungsreihenfolge, Überlauf, Transaktionen und fehlerhafte Frames.
`native/symbolic/core_tests.cpp` prüft Graphbudgets und die numerische Umgebung
direkt in C++. Ein fehlender C++-Compiler lässt diese Tests fehlschlagen.

Der Vergleich umfasst vier Edge-Formen und das 32-Räume-Beispiel, jeweils statisch,
mit einer Eingabeänderung und mit Änderungen aller Eingaben. Drei native Modi
rotieren innerhalb jedes Prozesses. Es gibt eine Aufwärmserie und 15 Messserien;
jede Serie mittelt mehrere abwechselnde Frames. NumPy wird mit denselben bereits
vorbereiteten Eingaben in angrenzenden Serien gemessen. Berichtet werden Rohzeiten,
Median, IQR und MAD. Der Vergleich mit NumPy ist ein Verhältnis von Medianen,
kein zeitlich verschachtelter Paarvergleich.

Die nativen Kernzeiten enthalten keinen Prozessstart und keinen Binär-/JSON-
Transport. Die geprüften C++-Pfade enthalten Größen-/Umgebungsprüfung,
Inhaltsvergleich, erforderliche Endlichkeitsprüfungen, Eingabekopien, Berechnung
und transaktionale Übernahme. NumPy allokiert seine Ergebnisse; C++ stellt bereits
reservierten Speicher bereit. Das ist ein Architekturvergleich mit expliziten
Kosten, keine isolierte Messung allein des Sprach-Overheads.

Der vollständige Rasterizer ist weiterhin nicht nach C++ portiert. Dieser Slice
ersetzt die Ausführung des symbolischen Forschungsgraphen. Framebuffer, Culling,
Shader-Aufrufe und Gesamtbildrate werden durch diese Mikrobenchmarks nicht bewertet.
Ein unbegrenzter Stream und parallele Worker sind ebenfalls nicht implementiert.

## Gemessener Stand vom 11.10.2026

AMD EPYC 9V74, GCC 13.3.0, portable Compiler-Flags, ein Worker. Jede Zeile hat 15 Messserien. Werte größer 1 bedeuten schneller als die direkte NumPy-Referenz.

| Aufgabe | Änderung | Reiner C++-Kern | C++ geprüft, vollständig | C++ geprüft, inkrementell |
| --- | --- | ---: | ---: | ---: |
| edge 2×2×3 | unverändert | 393.66× | 90.34× | 91.07× |
| edge 2×2×3 | eine Eingabe | 249.16× | 55.25× | 42.05× |
| edge 2×2×3 | alle Eingaben | 287.46× | 49.92× | 32.35× |
| edge 16×16 | unverändert | 17.30× | 11.22× | 29.72× |
| edge 16×16 | eine Eingabe | 17.25× | 10.19× | 11.13× |
| edge 16×16 | alle Eingaben | 16.59× | 7.14× | 5.03× |
| edge 64×64 | unverändert | 1.93× | 1.20× | 3.36× |
| edge 64×64 | eine Eingabe | 2.12× | 1.23× | 1.25× |
| edge 64×64 | alle Eingaben | 3.07× | 1.43× | 0.89× |
| edge 256×256 | unverändert | 1.29× | 0.74× | 1.78× |
| edge 256×256 | eine Eingabe | 1.46× | 0.77× | 0.77× |
| edge 256×256 | alle Eingaben | 1.27× | 0.63× | 0.35× |
| rooms-32 1 | unverändert | 690.16× | 80.19× | 84.52× |
| rooms-32 1 | eine Eingabe | 644.48× | 86.70× | 73.51× |
| rooms-32 1 | alle Eingaben | 616.02× | 71.12× | 36.56× |

Die sehr großen Faktoren der winzigen Aufgaben entstehen beim Vergleich vieler einzelner NumPy-Aufrufe mit einem kompilierten Auftrag. Sie dürfen nicht als Gesamtbildraten-Gewinn gelesen werden. Bei 256×256 Werten gewinnt der reine Kern 1,27–1,46×; der vollständige geprüfte Pfad verliert bei geänderten Eingaben weiterhin. Der statische inkrementelle Pfad erreicht dort 1,78×. Automatische Wahl der Ausführung ist nicht kalibriert.

225 lokal ausführbare Tests bestehen, darunter neun neue Tests mit tatsächlicher C++-Kompilierung. Die Python-Coverage beträgt insgesamt 68,06%, im Offline-Generator 99%; alle bestehenden Floors und der neue 90%-Floor bestehen. Genau der hostblockierte AF_UNIX-Test und sein verschachtelter vollständiger Coverage-Lauf wurden lokal ausgenommen; die Floors wurden im tatsächlich ausgeführten lokalen Lauf direkt geprüft. Zwei optionale LLVM-Tests überspringen wegen fehlendem JIT-Extra. Die vollständige CI wird am veröffentlichten Head separat geprüft.

Der native Header erreicht in GCC/gcov 100.00% ausgeführte Zeilen durch echte C++-Invarianten- und Edge-Läufe. ASan/UBSan melden in den nativen Invariantentests keine Fehler. LeakSanitizer konnte wegen der Host-Sicht auf `/proc/.../task` nicht laufen; der erfolgreiche Speicher-/UB-Lauf verwendete ausdrücklich `detect_leaks=0`.

Ein separates Programm wurde mit unerreichbarem PATH/PYTHONHOME/PYTHONPATH auf echte Edge-Eingaben ausgeführt; die Ergebnisbits stimmen. Die dynamischen Abhängigkeiten enthalten C/C++-Systembibliotheken und keine Python-Bibliothek. GCC bestätigt 16-Byte-Vektorisierung des zusammengefassten Kerns.

Rohmessungen, Build- und Quellhashes sowie die unabhängige Paritätsprüfung stehen in `evidence/native-symbolic-core-v1.json`. Dessen `git_head` ist die Basis des gemessenen Arbeitsstands; die enthaltenen Quellhashes binden die tatsächlich gemessenen neuen Dateien. Die veröffentlichten Quelldateien müssen diese Hashes unverändert erfüllen.

Bewertung: Python ist aus diesem Berechnungspfad entfernt. Die native Architektur löst das Aufrufproblem kleiner Aufgaben; bei großen wechselnden Daten bleiben Datenübernahme und Validierung entscheidend. Eine Aktivierung im vollständigen Renderer braucht weiterhin echte Szenen und einen gemessenen Integrationspfad.
