# C++-Direktpfad mit Prüfung im Rechendurchlauf

Der zusätzliche Modus `run direct` beseitigt Eingabekopien und Inhaltsvergleiche
im vollständig neu berechnenden symbolischen C++17-Pfad. Bei großen wechselnden
Edge-Eingaben war dies der gemessene Engpass nach PR #32. Der bisherige `fused`-
und der inkrementelle Cache-Pfad bleiben verfügbar. Kein automatisches Gate.

## Vertrag und Verwendung

```bash
./build/native-edge/kernel run direct < frames.bin
```

Der Offline-Bau bleibt wie in [NATIVE_SYMBOLIC_CORE.md](NATIVE_SYMBOLIC_CORE.md).
Ein neu gebauter Kern enthält alle drei Ausführungsmodi. Python wird einmalig
zum Prüfen/Erzeugen der Quellen benutzt und ist nicht im nativen Rechenprozess.

`are::DirectEngine` leiht den zusammenhängenden Float32-Eingabevektor nur für die
Dauer des synchronen `evaluate()`-Aufrufs. Der Aufrufer muss ihn währenddessen
unverändert gültig halten; gleichzeitige Mutation ist nicht erlaubt. Die Engine
behält keinen Eingabezeiger über diesen Aufruf hinaus. Der Graph samt generierter
Funktionen muss unverändert bleiben und die Engine überleben.

Die Engine besitzt genau zwei Datenpuffer je Ausgabe. Es gibt keine Puffer für
Eingaben oder Zwischenknoten. Der normale Rechenschritt allokiert nicht. Beim
256×256-Edge-Graphen sind das 0,5 MiB statt 6,5 MiB reservierter Float32-Puffer;
Eingaben des Aufrufers und Verwaltungsobjekte sind in dieser Strukturrechnung
nicht enthalten. Dies ist keine Messung des Prozess-RSS.

Die generierte Schleife prüft **alle Eingaben**, einschließlich ungenutzter und
als Ausgabe weitergereichter Eingaben, und alle Zwischenwerte auf Endlichkeit.
Float32-Operatorreihenfolge, Compiler-Flags und Graph-/Wire-Bindung bleiben gleich.
Bei ungültiger Eingabe gilt `NONFINITE_INPUT` vor `NONFINITE_RESULT`. Ergebnisse
werden erst nach erfolgreicher Prüfung aller Formen übernommen. Ein Fehler lässt
die letzte gültige Ausgabe unverändert. Ergebnisreferenzen gelten bis zum nächsten
erfolgreichen Frame. Wie bisher wird FE_TONEAREST verlangt, FTZ/DAZ abgewiesen.

Da der Direktpfad absichtlich keinen Inhaltsvergleich ausführt, meldet er
`changed_inputs: null`. `executed_nodes` zählt sämtliche Nicht-Eingabeknoten.
Die bisherigen Modi liefern weiter ihre tatsächlichen Änderungszähler. Das
Protokoll bleibt v1; das neue null betrifft ausschließlich den expliziten neuen
Modus. Der rohe Benchmarkkern setzt weiter vorab geprüfte Eingaben voraus.

## Laufzeitmessung vom 11.10.2026

AMD EPYC 9V74, GCC 13.3.0, ein Worker, unveränderte portable Compiler-Flags ohne
Fast-Math oder FMA-Kontraktion. 20 Messserien je Fall, ein Warm-up, vier native
Modi in rotierter Reihenfolge. Der native Faktor ist der Median der Verhältnisse
innerhalb derselben Wiederholung; IQR ist die Streuung dieser Verhältnisse.
Zeiten sind Median in Mikrosekunden je Frame. Die NumPy-Spalte ist dagegen das
Verhältnis separat gemessener Mediane, kein gepaarter Vergleich.

| Aufgabe | Änderung | bisher geprüft µs | direkt geprüft µs | gepaarter Faktor | Faktor-IQR | NumPy / direkt |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| edge 2×2×3 | static | 0.066 | 0.035 | 1.868× | 0.017 | 99.311× |
| edge 2×2×3 | one-input | 0.068 | 0.035 | 1.966× | 0.024 | 104.941× |
| edge 2×2×3 | all-inputs | 0.088 | 0.035 | 2.523× | 0.105 | 103.165× |
| edge 16×16 | static | 0.396 | 0.459 | 0.863× | 0.199 | 9.825× |
| edge 16×16 | one-input | 0.425 | 0.459 | 0.924× | 0.124 | 8.804× |
| edge 16×16 | all-inputs | 0.602 | 0.459 | 1.311× | 0.005 | 8.927× |
| edge 64×64 | static | 6.981 | 8.208 | 0.873× | 0.124 | 1.646× |
| edge 64×64 | one-input | 7.890 | 8.156 | 0.991× | 0.122 | 1.588× |
| edge 64×64 | all-inputs | 11.140 | 8.224 | 1.358× | 0.204 | 1.749× |
| edge 256×256 | static | 263.051 | 167.477 | 1.516× | 0.329 | 0.887× |
| edge 256×256 | one-input | 220.014 | 137.245 | 1.641× | 0.163 | 1.164× |
| edge 256×256 | all-inputs | 221.304 | 136.361 | 1.596× | 0.172 | 1.208× |
| rooms-32 1 | static | 0.388 | 0.104 | 3.671× | 2.851 | 382.349× |
| rooms-32 1 | one-input | 0.385 | 0.106 | 3.622× | 0.178 | 355.876× |
| rooms-32 1 | all-inputs | 0.481 | 0.103 | 4.627× | 0.458 | 354.598× |

Bei 256×256 geänderten Daten beträgt der gepaarte native Gewinn 1,60–1,64×.
Der Direktpfad erreicht gegen NumPy 1,16–1,21×. Die Zeitserien streuen auf diesem
Host; Rohwerte, IQR und unskalierte MAD werden mitgeliefert. Ein einzelner Lauf
ist kein universeller Hardware- oder Szenennachweis. Bei unveränderten großen
Eingaben ist der inkrementelle Cache schneller. Bei 16×16 und statischer/einzelner
Änderung verliert der Direktpfad gegenüber dem bisherigen Fused-Pfad. Es wird
deshalb keine pauschale automatische Auswahl aktiviert. Auch der statische
256×256-Direktpfad liegt in diesem Lauf unter der NumPy-Referenz.

Native Zeiten enthalten Größen-/Umgebungsprüfung, alle erforderlichen
Endlichkeitsprüfungen, Berechnung und transaktionale Übernahme. Keine
Prozessstarts, Wire-Dekodierung oder JSON-Ausgabe im Zeitfenster. NumPy allokiert
Ausgaben, C++ verwendet reservierte Puffer. Beide benutzen dieselben residenten
Eingabepaare. `one-input` ändert nur das erste Element von `px` (Edge) bzw.
`x0` (Räume) um 0,0625; `all-inputs` addiert diesen Wert zu allen Elementen
aller Eingaben. `static` verwendet zwei bitgleiche Frames. Jeder Fall wurde vor der Messung gegen echte Renderer-Edge-Functions
bzw. die explizite Raum-Reduktionsreferenz auf alle Ergebnisbits geprüft.

## Nachweise und Grenzen

Elf native Testmethoden kompilieren und starten wirkliche C++-Programme. Die
Erweiterung prüft NaN/±Inf in jeder Eingabe, ungenutzte Eingaben anderer Form,
Input-only-Graphen, Fehlervorrang, Rollback, unbekannte Änderungszähler und volle
Neuberechnung. Bestehende Paritätstests laufen zusätzlich im Direktmodus:
24 Seeds, mehrere Formen/Ausgaben, Subnormals, signierte Null und feste
Rundungsreihenfolge. Native Invarianten prüfen Lebensdauer der Eingaben, alten
Ausgabestand bei Fehlern, Rundungsmodus/DAZ und null Allokationen in 100 gültigen
Direktaufrufen.

Die endgültige lokale Suite umfasst 227 ausgeführte Tests mit zwei optionalen
LLVM-Skips; alle Coverage-Floors bestehen (68,06% Python gesamt, 99,01% im
Offline-Generator). Der volle Workbench-Lauf scheitert lokal am verbotenen
AF_UNIX-Socket und dadurch an seinem verschachtelten Coverage-Wrapper. Genau
diese zwei Tests wurden im lokalen Floor-Lauf ausgenommen. Ein früherer
Floor-Lauf hatte außerdem einen wechselhaften bestehenden CPU-Budget-Abbruch
(`WORKER_CRASHED:exitcode=-9`); gezielter Wiederholungslauf und finaler Suite-Lauf bestehen.
Fehllauf und Wiederholungen bleiben im ergänzenden Prüfarchiv erhalten.

Der erzeugte Direkt-Kern rechnet mit unauffindbarem PATH/PYTHONHOME/PYTHONPATH
korrekte Edge-Bits; seine dynamischen Abhängigkeiten enthalten kein Python.
Native Invarianten und der generierte Direkt-Kern bestehen ASan/UBSan. Dabei ist
LeakSanitizer ausdrücklich abgeschaltet (`detect_leaks=0`), weil die Host-Sicht
auf `/proc/.../task` dessen Prüfung verhindert. GCC meldet 16-Byte-Vektorisierung
für beide Varianten der generierten Schleife.

Der zusätzliche vollständige Flächenplan-Benchmark besteht: fünf Szenen × acht
Modi × (15 Wiederholungen + Warm-up) = 640 echte Draws bei 256 px; sämtliche
Farb- und Tiefenbytes stimmen überein. Workbench-Ausführung, Artifact-Audit und
Quellhash-Abgleich bestehen. Dieser unveränderte Renderer-Pfad ruft den neuen
symbolischen Kern nicht auf; seine Zeiten sind ein Regressionstest und kein
Leistungsgewinn durch diesen Patch.

[evidence/native-direct-inputs-v1.json](../evidence/native-direct-inputs-v1.json)
enthält alle 15 Fälle, Zeitserien, Host-/Build-Informationen und Quellhashes vor
und nach dem Lauf. `git_head` benennt die Basis vor dem Commit; die Quellhashes
binden die tatsächlich gemessenen Änderungen. Die vollständige CI ist am
veröffentlichten PR-Head nachzuweisen.

Dieser Slice betrifft den symbolischen Berechnungskern. Er portiert nicht den
vollständigen Rasterizer, erweitert nicht die unterstützte Wolfram-Sprache und
belegt keine Gesamt-FPS oder Gleichwertigkeit mit einer Gaming-GPU.
