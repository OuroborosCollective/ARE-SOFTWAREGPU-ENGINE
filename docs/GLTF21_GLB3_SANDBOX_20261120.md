# glTF 2.1 / GLB v3: opt-in Inspektions-Sandbox (Arbeitsentwurf, nicht ratifiziert)

**Stand: 20. November 2026 · Issue #284.** Diese Sandbox liest Dateien im Entwurfsformat „GLB Version 3“ ausschließlich zu Diagnosezwecken. Sie ist kein Importer, lässt kein Asset für den Renderer zu und ändert den GLB‑2.0‑Standardpfad nicht.

## Status der Spezifikation (gegen Khronos-Quellen gelesen)

glTF 2.1 und der 64‑Bit‑Container „GLB v3“ sind **angekündigt, aber nicht veröffentlicht und nicht ratifiziert**. Das Bytelayout kann sich noch ändern.

| Quelle (gelesen am 2026‑11‑20) | Befund |
|:--|:--|
| [Khronos glTF Registry](https://registry.khronos.org/glTF/) | „The current version of glTF is 2.0“ (2.0.1); kein 2.1‑Eintrag |
| [Khronos-Blog vom 11.06.2026](https://www.khronos.org/blog/introducing-gltf-2.1-with-complex-scenes) | kündigt „plans for glTF 2.1“ an; „Stay tuned … as we approach the release“ |
| [Tracking-Issue KhronosGroup/glTF#2585](https://github.com/KhronosGroup/glTF/issues/2585) | offen, 0 von 14 Teil-Issues erledigt; „under active development … normative text to follow“ |
| Branch `draft-2.1` @ `c330f9e5a324c9858145be183d2a1e63718fd3e8` | `specification/2.1/Specification.adoc`, SHA‑256 `83e76b6e…ebecd1`; auf `main` existiert die Datei nicht |
| [Issue #2594 (64‑Bit-Binärformat)](https://github.com/KhronosGroup/glTF/issues/2594) | Community-Beispieldateien ausdrücklich „No guarantees“; keine offiziellen Konformitäts-Assets |

Vollständiger Readback mit allen Hashes: [`evidence/gltf21-glb3-khronos-status-20261120.json`](../evidence/gltf21-glb3-khronos-status-20261120.json). Mindestens ein Drittbericht nennt glTF 2.1 „offiziell veröffentlicht“; die Khronos-Quellen widersprechen dem.

**Interoperabilität: nicht hergestellt.** Die bereits gemergte Entwurfs-Implementierung in `visgl/loaders.gl` (Commit `a4faaba2…`) richtet Chunks auf **4 Byte** innerhalb von `chunkLength` aus. Der Khronos-Entwurf verlangt **8‑Byte**-Chunk-Starts mit Padding außerhalb von `chunkLength`. Beide Layouts stimmen nur überein, wenn die aufgefüllte Länge jedes Chunks, auf den ein weiterer folgt, ein Vielfaches von 8 ist (der letzte Chunk ist frei). Die Sandbox folgt dem gepinnten Khronos-Text und weist das abweichende Layout ab, ohne es zu erraten.

## Vertrag

Zugang gibt es nur mit der exakten Vertragskennung **`are.gltf21-glb3-sandbox.v1`**. Es gibt keinen Standardwert.

```
python -m tools.gltf21_glb3_sandbox ENTWURF.glb --contract are.gltf21-glb3-sandbox.v1
```

```python
from tools.gltf21_glb3_sandbox import CONTRACT, inspect_glb3_sandbox
receipt = inspect_glb3_sandbox(data, contract=CONTRACT)   # oder SandboxRejection
```

Die Kommandozeile liest nur reguläre Dateien (keine Symlinks, Geräte oder Pipes) und höchstens 64 MiB. `--output DATEI` legt die Receipt-Datei **exklusiv neu** an: Ein bestehender Pfad wird mit `OUTPUT_EXISTS` abgelehnt – auch die geprüfte Datei selbst oder ein Hard- bzw. Symlink darauf. Die Quelle wird nie verändert.

Die Kennung ist an genau den gelesenen Entwurfsstand gebunden (`SPEC_BASIS` im Modul). Ein späterer Entwurf oder ein ratifizierter Text braucht eine neue Vertragsversion mit neuem Readback.

Jedes Receipt enthält `specification.ratified: false`, `runtime_admission: "refused"`, `verdict: "not_assessed"`, die SHA‑256 der Quelle und jedes Chunk-Payloads, die beobachteten Entwurfsmerkmale sowie alle Grenzen.

## Getrennt vom GLB‑2.0‑Pfad

- `tools/glb_container_preflight.py` ist unverändert; ein Test pinnt seine SHA‑256 und ein eingefrorenes Entscheidungsprotokoll über echte GLB2-Bytes.
- Der GLB2-Preflight lehnt jede v3-Datei weiterhin ab. Die Sandbox lehnt jede v2-Datei mit `VERSION_2_OUT_OF_SCOPE` ab.
- Die Sandbox importiert nur `argparse`, `hashlib`, `json`, `math`, `pathlib`, `re`, `struct`. Kein Laufzeitmodul, kein `main.py`, kein nativer Renderer verweist auf sie.

## Geprüfte Regeln (fail-closed)

| Bereich | Verhalten |
|:--|:--|
| Byte-Reihenfolge | nur Little-Endian; Big-Endian-Dateien → `BIG_ENDIAN_REFUSED`, kein Erraten |
| 64‑Bit-Längen | höchstwertiges Bit gesetzt → `LENGTH_MSB` / `CHUNK_LENGTH_MSB`; Längen werden nie addiert, sondern gegen den Rest verglichen → `CHUNK_LENGTH_OVERFLOW`; deklarierte Länge ≠ Dateigröße → `LENGTH_MISMATCH` |
| Abschneiden | jedes echte Präfix einer gültigen Datei wird abgewiesen (deklarierte Länge ≠ Größe). Mit nachträglich korrigierter Länge bleibt nur gültig, was für sich eine gültige Datei ist – etwa ohne End-Padding oder ohne einen vom JSON nicht referenzierten letzten Chunk |
| Chunk-Encoding | nur `0`; jeder andere Wert → `CHUNK_ENCODING_REFUSED`, das Payload wird nicht berührt |
| Kompression | gzip/zstd/xz/bzip2/zip-Signaturen → `COMPRESSED_INPUT_REFUSED`; nichts wird entpackt, Bilder, Data-URIs und Extension-Payloads werden nicht dekodiert |
| JSON | striktes UTF‑8 ohne BOM, keine doppelten Schlüssel, kein `NaN`/`Infinity`, keine einzelnen Surrogate, Tiefe ≤ 64, höchstens 524 288 Strukturzeichen (`[`, `{`, `,`) und 2 097 152 Anführungszeichen – eine vorsichtige Obergrenze für die Zahl der Werte, die auch Zeichen innerhalb von Strings mitzählt –, Ganzzahlen ≤ 20 Stellen; Ganzzahlen dürfen wie im Entwurf als `8.0` oder `1e2` geschrieben sein, ein Nachkommaanteil wird abgelehnt |
| Schema | `asset.version` nur `2.0`/`2.1`, `minVersion` ≤ `version`; `buffers`/`chunk`-Bindung; BufferView- und Accessor-Grenzen exakt, Offsets und Stride als Vielfache der Komponentengröße, Stride ≤ BufferView-Länge, kein Accessor-Offset ohne BufferView; Bilder mit genau einer Quelle |
| Externe Ressourcen | werden nur gezählt (≤ 256 Verweise, URI ≤ 2048 Zeichen, Data-URIs ≤ 1 MiB), **nie** geöffnet oder geladen: `external_resolution.policy = "never"`. Gezählt wird, was ein Loader auflösen würde: Rand-Leerzeichen und Steuerzeichen entfernt, `%2e`/`%2f`/`%5c` dekodiert |
| Budgets | Quelle ≤ 64 MiB, ≤ 64 Chunks, JSON-Chunk ≤ 4 MiB, ≤ 256 Erweiterungsnamen zu je ≤ 128 Zeichen, Medientyp ≤ 255 Zeichen, Ganzzahlwerte ≤ 2^53. Jedes Budget steht in `limits` jedes Receipts |

Strenger als der Entwurf (bewusst):

- Ein Nicht-Null-Encoding auf *irgendeinem* Chunk verweigert die ganze Datei (Entwurf: nur der betroffene Chunk bzw. der Haupt-JSON-Chunk).
- Unbekannte `asset`-Versionen werden nicht „vorwärtskompatibel“ akzeptiert.
- Doppelte JSON-Schlüssel werden abgelehnt (Entwurf: sollen eindeutig sein, sonst gilt der letzte Wert).
- Zahlen, die einen Double überlaufen (`1e400`), `NaN`/`Infinity` und einzelne Surrogat-Escapes werden abgelehnt; Ganzzahlen mit mehr als 20 Stellen ebenfalls.
- Unbekannte `componentType`- und `type`-Werte von Accessoren werden abgelehnt (der Entwurf überlässt weitere Werte Erweiterungen).
- `chunk` und `uri` zugleich an einem Buffer ist ein Fehler; ein `files`-Eintrag braucht genau eine Quelle.
- Größen über 2^53 werden abgelehnt (Entwurf: sollen vermieden werden).
- Nach dem letzten Chunk sind nur Füllbytes bis zur nächsten 8‑Byte-Grenze erlaubt.
- Alle Budgets oben sind Ablehnungsgründe; der Entwurf kennt solche Obergrenzen nicht.

## Nachweise

| Abnahmepunkt aus #284 | Test |
|:--|:--|
| GLB2-Parser unverändert und disjunkt | `Glb2DisjointnessTests` |
| Big-/Little-Endian, 64‑Bit-Overflow, Abschneiden | `EndiannessAndLengthTests`, `TruncationTests` |
| JSON-Schema, UTF‑8, BufferView-Grenzen | `JsonAndBoundsTests` |
| gzip-/Dekompressionsbomben | `DecompressionBombTests` (echte Bombe, gemessener Speicher-Peak) |
| Limits für extern aufgelöste Ressourcen | `ExternalResourceTests` (Audit-Hook: kein Datei-, Netz- oder Prozesszugriff) |
| keine Ratifikationsbehauptung | `RatificationClaimTests` |
| Python-/Native-Fuzz-Negativtests, Windows/Linux | `test_gltf21_glb3_fuzz.py` |
| SHA-gepinnte Decode-Receipts | [`evidence/gltf21-glb3-sandbox-receipts-v1.json`](../evidence/gltf21-glb3-sandbox-receipts-v1.json) |
| unabhängige bekannte Testassets | [`evidence/gltf21-glb3-independent-assets-v1.json`](../evidence/gltf21-glb3-independent-assets-v1.json) |

```
python -m unittest software_gpu.tests.test_gltf21_glb3_sandbox \
    software_gpu.tests.test_gltf21_glb3_fuzz \
    software_gpu.tests.test_gltf21_glb3_independent_assets -v
```

**Differenzial-Fuzzing.** Der Framing-Teil existiert zweimal: in Python und unabhängig in C++17 (`native/gltf/glb3_container_probe.cpp`, byteweise Dekodierung, daher unabhängig von der Host-Byte-Reihenfolge). Beide müssen für jede Eingabe dasselbe Urteil liefern: 4000 gesäte Mutationen, 1500 JSON-Mutationen, alle 15 104 Ein-Byte-Änderungen der Minimaldatei sowie gezielte Grenzfälle. Korpus- und Urteils-SHA‑256 sind gepinnt und auf Python 3.11, 3.12 und 3.13 identisch.

**Unabhängige Assets.** Vier Khronos-Beispielassets (`Box`, `BoxInterleaved`, `BoxTextured`, `BoxVertexColors`, CC‑BY‑4.0) sind per Commit, Größe und SHA‑256 gepinnt und werden **nicht** im Repository gespeichert. Der Replay prüft je Asset: unveränderter GLB2-Preflight akzeptiert, Sandbox verweigert v2, und dieselben JSON-/BIN-Payloads im Entwurfscontainer ergeben identische Payload-Hashes.

```
python -m tools.gltf21_glb3_independent_assets --assets-dir /tmp/khronos-glb2 --fetch
```

Für v3 selbst gibt es keine offiziellen Assets. Zwei unabhängige Layoutquellen sind als Vektoren nachgebaut: die im Khronos-Issue #2594 abgedruckte Layouttabelle (sechs Füllbytes sind dort nicht veröffentlicht, daher kein Byte-Abbild des Community-Archivs) und der Fixture-Writer von loaders.gl.

## Grenzen

- Keine Konformitäts-, Interoperabilitäts- oder Ratifikationsaussage; keine Zeit-, FPS- oder Ranglistenmessung.
- Das Community-Archiv `GLBv3-2026-10-10.zip` konnte in der Erstellungssitzung nicht geladen werden und ist nicht gepinnt.
- Die native Probe prüft nur das Framing und UTF‑8, nicht das JSON-Schema. Sie lief auf Little-Endian-Hosts; ein Big-Endian-Host wurde nicht ausgeführt.
- `externalAssets`-Zyklen werden nicht ausgewertet, weil nichts geladen wird (`external_asset_cycles: "not_evaluated"`).
- Sparse-Accessoren und Extension-Inhalte werden gezählt, nicht geprüft.

## Projektflächen

- **Production:** unverändert; kein Standardpfad nutzt die Sandbox
- **Test:** drei neue Testmodule, eine native C++17-Probe, gesäte Fuzz-Korpora
- **Persistence:** drei Evidence-Dateien und der Testreihen-Katalog; keine Spielstände
- **Effects / Core / Runtime projection:** unverändert

**Merge-Gate:** exakte Head-CI (Linux/Windows, Python 3.11/3.12) einschließlich der neuen Module, genau ein `Memory.md`-Eintrag, unabhängiger GitHub-Readback.
