# Wolfram-Scanner und symbolische Berechnungswellen

Forschungszweig auf Basis von `339dd8dd703971612839fb95db7e4b84c53d81a9`.
Der Renderer importiert diese Forschungsbausteine nicht. Der Vorbereitungs-Cache
aus PR #31 ist ein eigenständiger Versuch und wird hier nicht vorausgesetzt.

## Was umgesetzt ist

| Baustein | Tatsächliche Funktion | Grenze |
| --- | --- | --- |
| Wolfram-Scanner | `ToExpression[..., InputForm, HoldComplete]`, anschließend Prüfung unserer `ARETaskGraph`-Grammatik, Typen und DAG-Abhängigkeiten | Unterstützt `input`, `add`, `sub`, `mul`; beliebige Wolfram-Programme werden abgewiesen |
| Mehrdimensionale Punkte | Vier Koordinaten im Beispiel; bis acht Koordinaten erlaubt | Metadaten zur Anordnung, keine zusätzliche Hardware-Rechenleistung |
| Tensoren | Elementweise Float32-Rechnung, bis vier Formdimensionen | Gleiche Formen; keine implizite Typkonvertierung oder Broadcasting |
| Farbige Gruppen | Grau: Eingabe; Grün: Addition; Blau: Subtraktion; Orange: Multiplikation | Gruppiert wird nach Operator, Typ, Form und Rechenvertrag; Farbe allein reicht nicht |
| Berechnungswellen | Nur Knoten mit erledigten Vorgängern werden gebündelt | Reiner DAG, keine Zyklen oder globales Weltwissen |
| Änderungsscan | Inhalts-Hash aller Eingaben, danach nur abhängige Rechenknoten neu auswerten | Vollständiger Eingabescann kostet Zeit; derzeit ein Worker |
| Codeausgabe | Python/NumPy und JavaScript mit `Math.fround` nach jedem Operator | Kein allgemeiner Übersetzer nach C++, Rust oder beliebigen Zielsprachen |
| Prüfstufe vor Auslieferung | Exakt generierten Zielcode gegen mitgelieferte unabhängige Orakelfälle ausführen; Quellhashes im Receipt | Fehlende Zielruntime, Zeitüberschreitung oder Abweichung blockiert die Ausgabe |

Der Graph hat höchstens 128 Knoten und insgesamt höchstens 1.048.576
Tensorzellen über alle Knoten. Der Wolfram-Scanner begrenzt die Quelltextlänge
auf 65.536 Zeichen. Die Auslieferungsprüfung akzeptiert 1–32 Orakelfälle;
der JavaScript-Zeitrahmen gilt je Fall, nicht als Prozess-RSS-Garantie.

## Zwei echte Beispiele

Die Renderer-Edge-Funktion wird als 13-Knoten-Graph mit sechs Eingaben und sieben
Rechenknoten dargestellt. Vier Subtraktionen, zwei Multiplikationen und die letzte
Subtraktion bilden drei Wellen. Der Beispiel-Tensor hat Form `2×2×3`.
Eine Änderung an `px` invalidiert `rx`, `left` und `edge`: drei von sieben
Rechenknoten. Unveränderte Eingaben führen zu keiner erneuten Rechenknoten-Auswertung.

Das Raum-Muster hat 32 unabhängige Multiplikationen und eine feste binäre
Additions-Zusammenführung. Es umfasst 127 Knoten, sechs Wellen und 63 Rechenknoten.
Eine Änderung an einer Eingabe von Raum 0 invalidiert dessen Multiplikation und
die fünf Additionen zum Ziel: sechs von 63 Rechenknoten. Die feste Reihenfolge
ist Teil des Float32-Vertrags; eine beliebige Summenreduktion wäre kein gültiger Ersatz.

Wolfram und Python bestimmen unabhängig dieselben Edge-Wellen. Ein separater
exakter Wolfram-Algebratest bestätigt die Formel. Die Float32-Bytegleichheit kommt
aus den realen numerischen Tests gegen `graphics.geometry.edge_function`;
die symbolische Identität erlaubt keine Umordnung gerundeter Operationen.

## Was der vorgeschlagene Million-Räume-Code zeigt

`ParallelMap` verteilt gleiche Funktionen über vorhandene Parallel-Kernel.
Eine Liste mit einer Million IDs erzeugt keine Million gleichzeitig laufender
Prozesse. `Take[..., 10000]` verwendet bei einer Million Ergebnissen nur ein
Prozent; `Partition` ordnet diese Werte zu einer Matrix. `ArrayPlot` färbt
Ergebniswerte und klassifiziert damit keine Berechnungsarten.

Der ausgeführte, begrenzte Wolfram-Probelauf mit 1.024 Werten liefert eine
32×32-Matrix und ein `Graphics`-Ergebnis. Serielle und `ParallelMap`-Werte sind
gleich. Der Provider meldet aber null Parallel-Kernel: echte Parallelität ist
hier nicht nachgewiesen. Die einzelne ParallelMap-Probe war langsamer; daraus
wird keine allgemeine Leistungsaussage abgeleitet. Die Maschinenzahl-Variante
und die ursprüngliche `N[Sin[i] Cos[i]]`-Form stimmen in den 32 geprüften
Beispielwerten überein. Diese f64-Trigonometrie ist kein Operator unseres f32-DAGs.

Die kopierte `###`-Überschrift ist überraschend syntaktisch gültig: Wolfram liest
sie als Produkte mit Slots und Symbolen. Sie ist kein Kommentar. Das demonstriert,
warum Syntaxprüfung und semantische Freigabe getrennte Prüfschritte brauchen.

## Prüfung vor der Auslieferung

`research/scan-symbolic-source.wl` liest Quelltext gehalten ein und gibt nur für
die erlaubte Aufgabengrammatik ein IR mit Status `PASS` aus. Im echten Provider-Test
wurden Zuweisung, unbekannter Operator, Zyklus, fremdes Programm, unbekannte Ausgabe
und übergroßer Quelltext blockiert. Die gehaltene Zuweisung änderte die Probevariable
nicht. Es wird kein `ReleaseHold` auf Eingaben angewendet.

`research/pre_delivery_scan.py` prüft das IR unabhängig und führt exakt die
generierten Python-/JavaScript-Quellen aus. Für den frisch von Wolfram gescannten
Graphen bestanden beide Zielsprachen zwei unabhängige Renderer-Orakelfälle.
Erst danach wurden die Quellen mit ihrem SHA-256 ausgegeben. CI benötigt keinen
Wolfram-Provider: gespeicherte Parser-Ergebnisse sind Prüfbeispiele, keine
Beglaubigung später veränderter IRs.

Das Receipt hält Struktur, Abhängigkeiten, numerische Fallprüfung und externe
Sachverhalte auseinander. Die numerische Prüfung gilt für die gelieferten Fälle;
`external_world` bleibt `unknown`. Die gewöhnliche WaveRuntime meldet ohne
externes Orakel weiterhin `oracle-unchecked`.

Der separate CodeTools/CAG-Adapter lieferte bei `parse` kein gültiges JSON und
ist als blockiert dokumentiert. Der ausgeführte gehaltene Wolfram-Kernel-Parser
funktioniert. Ein Erfolg des CodeTools-Adapters wird nicht behauptet.

## Ergebnisse und Reproduktion

Der Mikrobenchmark umfasst vier Edge-Tensorformen und das 32-Räume-Muster,
jeweils unverändert, mit einer Eingabeänderung und mit Änderungen aller Eingaben.
Pro Fall laufen drei rotierende Modi, ein Warm-up und 15 Wiederholungen:
675 gemessene Auswertungen. Alle Ergebnisbytes stimmen innerhalb eines Frames
überein. JSON enthält Rohzeiten, Median, IQR, unskalierten MAD, gepaarte Verhältnisse,
Seed, CPU-/NumPy-Umgebung, Frame-Hashes und Quellhashes.

Die generierte geprüfte NumPy-Version und die WaveRuntime sind in diesen einfachen
Rechenkernen langsamer als die direkte Referenz. Die Eingabeprüfung, Inhalts-Hashes
und Stapel-/Zwischenkopien dominieren. Die Referenz ist für Edge eine vorbereitete
ungeprüfte Kernfunktion, für Räume eine feste Python-Paarreduktion. Das ist eine
Vergleichsgrenze des Versuchs, keine Gesamt-Renderer- oder GPU-Messung.

```bash
python -m unittest software_gpu.tests.test_symbolic_wave software_gpu.tests.test_pre_delivery_scan software_gpu.tests.test_symbolic_wave_benchmark -v
python -m software_gpu.benchmarks.compare_symbolic_waves --root . --output symbolic-wave-benchmark.json --repeats 15
python -m unittest discover -s software_gpu/tests -v
```

Node.js muss für die JavaScript-Auslieferung verfügbar sein. Funktionstests
überspringen diese Zielruntime bei Fehlen ausdrücklich; eine angeforderte
Auslieferung nach JavaScript wird in diesem Fall blockiert. Die kanonische
Linux/Python-3.12-Lane prüft 95%-Coverage-Floors für Graph, Auslieferungsscan und
Benchmark. Die vollständige veröffentlichte CI wird separat am finalen Head gelesen.

## Code als fortlaufender Strom

Ein möglicher weiterer Schritt ist ein kompakter Strom aus Operator-IDs, Typen,
Formen, Abhängigkeitsindizes und Versionsnummern. Wiederkehrende typgleiche
Operationen könnten in begrenzten Abschnitten als Daten verarbeitet werden.
Ergebnisfreigabe braucht vollständige Abhängigkeiten, numerische Prüffälle und
Rückstaukontrolle. Ein Rasterbild kann diese Struktur anzeigen; es muss die
Codebedeutung nicht ersetzen. Ein unendlicher Stream, Pixel-Erkennung oder eine
neuronale Interpretation des Quellcodes ist in diesem Versuch nicht implementiert.

Die aussichtsreichste nächste Optimierung ist eine Ausführung mit weniger
Zwischenkopien und gröberem Arbeitspaket, unter Erhalt jeder f32-Operationsgrenze.
Anschließend sind größere Shader-Kerne und echte Szenen zu messen. Der vorliegende
Versuch liefert keinen Aktivierungsgrund und keinen Nachweis von Gaming-GPU-Parität.

## Primärquellen zur Einordnung

- [Wolfram ParallelMap](https://reference.wolfram.com/language/ref/ParallelMap.html): Verteilung auf vorhandene Kernel und Parallelisierungs-Overhead.
- [Wolfram ToExpression](https://reference.wolfram.com/language/ref/ToExpression.html): Parsing mit gehaltenem Ausdruck.
- [Wolfram ArrayPlot](https://reference.wolfram.com/language/ref/ArrayPlot.html): Visualisierung von Matrixwerten.
- [Static Batching of Irregular Workloads on GPUs, 27.01.2025](https://arxiv.org/abs/2501.16103): typbezogenes Batching und Task-/Tile-Zuordnung in CUDA. Die GPU-Ergebnisse sind nicht auf unseren CPU-Prototyp übertragen.
- [SET, 03.06.2026](https://arxiv.org/abs/2606.05495): eventgesteuerte DAG-Pipelines reduzieren Synchronisations- und Scheduling-Kosten auf GPU-Hardware. Hier nicht reproduziert.
- [egg](https://arxiv.org/abs/2004.03082): explizite Gleichheitsrelationen und Regeln für Ausdrucksoptimierung; eine passende Denkrichtung für Symbolerkennung.
- [MLIR](https://arxiv.org/abs/2002.11054): strukturierte Zwischenrepräsentationen und mehrstufige Codeübersetzung; hier als Einordnung, keine MLIR-Integration.
