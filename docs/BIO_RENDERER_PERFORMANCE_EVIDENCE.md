# Bio-Renderer — quellengebundener Leistungsnachweis / Bio renderer performance evidence

**Status:** Historische, quellengebundene CPU-auf-CPU-Messungen aus dem ARE-SOFTWAREGPU-ENGINE-Repository. **Keine unabhängige Zertifizierung**, kein Hardware-GPU-Vergleich und keine Leistungsattestierung durch GitHub. Ein signiertes Build-/Release-Attest bestätigt Herkunft/Integrität des Build-Artefakts, nicht dass ein Benchmark schneller ist.

## Drei unterschiedliche Vergleiche — bitte nicht vermischen

| Messreihe und Szenario | Baseline (Median, ms) | Kandidat (Median, ms) | Dokumentierter Gewinn | Exakter Gegner |
| --- | ---: | ---: | ---: | --- |
| AREMDL03 PBR, `animated4` (4 Modelle, 68.775 Dreiecke) | 96,420 | 60,774 | **1,587×** | native C++17-Baseline gegen native C++17-Bio-PBR (`combined`) |
| AREMDL03 PBR, `static2` (2 Modelle, 20.477 Dreiecke) | 21,167 | 13,621 | **1,554×** | dieselbe native PBR-Baseline |
| AREMDL03 PBR, `arena6` (6 Modelle, 89.252 Dreiecke) | 105,482 | 61,723 | **1,709×** | dieselbe native PBR-Baseline |
| Separater nativer Rastertest, 13.312 statische Dreiecke, 256 × 256 | 1.626,176 | 243,272 | **7,00× gepaarter Median** | **C++17 `native-cpp` gegen Python/NumPy-Batch-first**; **kein** AREMDL03-Bio-PBR-Test |

Die ersten drei Zeilen stammen aus [AREMDL03 Originalmodell-PBR-Bericht](native-pbr-arena-report-20261013.md) und [zugehörigen Messdaten](../evidence/native-pbr-20261013-fixed/benchmark/benchmark.json). Sie enthalten **15 abwechselnde Baseline-/Bio-Paare je Szene**, 3 Warmups, 256 × 256 Pixel, Tile 32, vier angeforderte CPU-Worker und volle RGBA-/Resolved-/Float32-Depth-Parität (`full_buffer_parity=true`). Der ausgewiesene Gewinn ist das im Bericht deklarierte Verhältnis für den jeweiligen Messlauf. Die Szenarien umfassen Originaltexturen, Skinning, perspektivisches PBR und lineares MSAA. **Das sind echte Bio-vs.-native-Baseline-Messungen, nicht Bio-vs.-NumPy-Messungen.**

Die vierte Zeile stammt aus [native-cpp-Rasterbericht](NATIVE_RASTER.md) und [15-Wiederholungen-Rohbeleg](../evidence/native-raster-v1.json). Sie prüft den vollständigen `draw_mesh`-Aufruf mit byteidentischen Farb-/Tiefenpuffern. Dieser C++17-VertexColor-Backendvergleich nutzt **eine andere Szene, andere Shader und einen anderen Messpfad** als die PBR-Arena. Der gepaarte Ratio-Median muss nicht dem Quotienten der separat angegebenen Timing-Mediane entsprechen. Eine Multiplikation dieser Speedups zu einem Gesamt-„Bio gegen NumPy“-Faktor wäre unbelegt.

### Weitere Bio-Messungen und Negativbefunde

- Eine frühere native Modell-Messreihe `AREMDL01/02` dokumentiert **2,543×** bei `arena6` und **2,777×** bei `all9` gegenüber der damaligen **nativen** Modell-Baseline: [Nachweis über wiederholte Modellläufe](../evidence/model-repeatability-v1.json), [Geltungsbereich und Methodik](native-model-benchmark.md). Diese Version verwendet diagnostische Modellbeleuchtung, **nicht** dieselbe PBR-Pipeline; Werte nicht als neuesten PBR-Speedup ausgeben.
- Bio-Workrooms mit 64 räumlich verteilten Dreiecken und 16er-Räumen erreichten gemäß [Bio-Workrooms-Methodik](BIO_WORKROOMS.md) in günstigen Varianten **1,28–1,33×** gegen die native Workrooms-Baseline. Mit millionenfach kleinteiligen Räumen oder stark überlappenden Dreiecken gab es teils **deutliche Verlangsamungen**. [Original-Bio-Messreihen](../evidence/bio-workrooms-summary-v2.json).
- Der PBR-`locality`-Vergleich senkte auf der gleichen `animated4`-Szene die Bio-Medianzeit von **60,631 auf 56,058 ms** (**7,5 %**); beide Varianten hatten `full_buffer_parity=true`. Achtung: Die `locality`-Zeile steht für einen **separaten Kontrolllauf**, nicht für die gesamte Szenario-Tabelle. [Bericht](native-pbr-arena-report-20261013.md), [Rohreceipts](../evidence/native-pbr-20261013-locality/benchmark/benchmark.json).

## Nachweisgrenze und Reproduzierbarkeit

Diese Ergebnisse beweisen, dass **bestimmte CPU-Renderer/Policies auf den angegebenen Szenen und Hosts schneller waren** als ihre jeweilige Referenz. Die gemessenen Bild-/Tiefen-Puffer stimmen in den angegebenen Läufen überein. Sie beweisen **nicht** generell, dass „Bio schneller als NumPy“ für alle GLBs, Shader, Auflösungen oder Geräte gilt; insbesondere existiert hier **kein identischer, end-to-end geprüfter AREMDL03-Bio-PBR-vs.-Python/NumPy-PBR-Rendertest**.

Zum Reproduzieren des PBR-Tests sind die SHA-256-gepinnten **Original-GLB-Binärdateien** erforderlich, die nicht Bestandteil des Repositories sind. Der Benchmark dokumentiert die Quellen- und Binärhashes, Buildflags, Workloads, Rohzeitreihen, Puffer-Hashes und Umgebungsgrenzen. Die geschützten Modelle können nicht durch eine frei erfundene Szene ersetzt werden, ohne den Messwert umzudeklarieren.

**Separate Gegenstände:** Ein GitHub-Release und dessen Provenance-Attestation beglaubigen ausschließlich, welcher Quellstand/Workflow ein Artefakt gebaut hat. Ein **Benchmark-Leistungsnachweis** muss die Messwerte und ihre Bedingungen separat belegen. Weder README noch Release-Text dürfen dies als unabhängig von Dritten zertifizierte Beschleunigung ausgeben.

## Kurzbeschreibung / Public claim

> Auf CPU-Originalmodell-Benchmarks erreichte die native C++17-Bio-PBR-Pipeline in drei manifestgebundenen Szenen **1,55–1,71×** gegenüber ihrer nativen Referenz, bei voller Farb-/Tiefen-Parität (je 15 gepaarte Frames). In einem **separaten** CPU-Rasterbenchmark erreichte der C++17-VertexColor-Backend-Pfad **7,00×** gegenüber der Python/NumPy-Batch-first-Variante auf 13.312 statischen Dreiecken bei 256 × 256 Pixeln. Keine Hardware-GPU-Parität oder pauschale Anwendungs-FPS-Zusage.
