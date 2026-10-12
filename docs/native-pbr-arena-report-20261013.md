# Native AREMDL03: perspektivische UVs, Originaltexturen und PBR

**Stand:** 2026-10-13 00:52 UTC · Branch `feat/reference-arena-frame-timings-20261012` · Draft-PR #48 · Profil `AREMDL03` / `render_profile=pbr`

## Ergebnis

Der native C++17-Modelpfad rendert nun die sechs privaten, manifestverifizierten Arena-GLBs in einer expliziten Perspektivkamera mit **perspektivisch korrekten UV-, Normalen- und Weltpositionsattributen**, Originaltexturen und einem begrenzten glTF-Metallic-Roughness-PBR-Profil. Die bestehende `ARERIN01`-/VertexColor-ABI und die Diagnose-/AREMDL01-/AREMDL02-Pfade bleiben getrennt und rückwärtskompatibel. Der neue Renderer ist opt-in; Python dekodiert und serialisiert GLBs offline, während Pose, Skinning, Clipping, Attributinterpolation, Mip-/Textursampling, GGX-Shading, lineares 4×MSAA, Tone Mapping, sRGB und FXAA nativ ablaufen.

### Implementierte Verträge

- `AREMDL03` ist ein versionierter, streng validierter Model-Input: Material-/Texture-/Image-/Sampler-IDs, `NORMAL`, `TEXCOORD_0`, feste Dimensions-/Pixel-/Mipbudgets und Frame-/Dreieckslimits werden vor bzw. während Allokationen geprüft.
- Der Importer akzeptiert ausschließlich eingebettete PNG-/JPEG-Ressourcen aus dem GLB-eigenen BIN-Chunk. Keine externen URI-Zugriffe. Nicht unterstützte `KHR_texture_transform`-Änderungen werden geschlossen abgewiesen; der Import bleibt im spezifizierten ein-Primitive-/`TEXCOORD_0`-Subset.
- Base Color wird als sRGB dekodiert und in linearem Licht gefiltert; Normal-/Metallic-Roughness-Daten bleiben linear. Mips, Wrap-/Min-/Mag-Filter, Normalmap-Scale, Materialfaktoren und stabile aus Positions-/UV-Ableitungen gebildete TBN-Basis sind in nativen Tests abgedeckt. Die sechs Originale enthalten keine exportierten Tangenten.
- Skinned und nichtuniform transformierte Normalen verwenden inverse-transponierte Normalentransformationen; der gewichtete Skinmatrixmix ist gegen eine unabhängige NumPy-Matrixoracle geprüft.
- Die Cook-Torrance-/GGX-Beleuchtung hat ein festgeschriebenes, begrenztes Arena-Lichtsetup. Der PBR-Ausgabepfad mittelt lineare Samplefarben vor Reinhard-Tone-Mapping/sRGB-Encoding; Diagnose-/Legacy-Farbpfade bleiben unverändert.
- Pillow ist als **optionales** `software_gpu[model-pbr]`-Extra deklariert. Der normale Legacy-Import lädt Pillow nicht, solange kein PBR-GLB-Bild dekodiert werden muss.

## Messprotokoll

Ausgeführt mit `tools/benchmark_models.py` gegen dieselben sechs vom Nutzer gelieferten Originalmodelle, 15 alternierende Baseline-/Bio-Paare je Case, drei Warmups, 256×256, Tile 32, vier CPU-Worker, feste serialisierte Perspektivkamera, `combined`-Policy und unveränderte Originaldateien. Die 15 Referenzphasen sind jetzt unabhängig von `repeats` festgeschrieben und werden bei längeren Läufen zyklisch wiederholt; damit bleibt der erste 15-Frame-Workload vergleichbar. Host: x86_64 Linux, AMD EPYC, sechs logische CPUs, GCC 13.3, C++17 `-O3 -fno-fast-math -ffp-contract=off`. **Kein Hardware-GPU-Submit.**

| Case | Modelle / Eingabedreiecke | Materialien / Maps | Native Baseline Median / p95 / Max (ms) | PBR Bio Median / p95 / Max (ms) | Median-Speedup | PBR Frames >16,7 ms |
|---|---:|---:|---:|---:|---:|---:|
| `animated4` | 4 / 68.775 | 4 / 12 | 96,420 / 104,613 / 113,601 | 60,774 / 63,451 / 65,621 | 1,587× | 15/15 |
| `static2` | 2 / 20.477 | 2 / 2 | 21,167 / 22,388 / 22,666 | 13,621 / 14,186 / 14,343 | 1,554× | 0/15 |
| `arena6` | 6 / 89.252 | 6 / 14 | 105,482 / 114,309 / 117,084 | 61,723 / 75,595 / 89,437 | 1,709× | 15/15 |

Jede Tabellenzeile hat `full_buffer_parity=true`, 15 ausgegebene Framehashes, stabile Source-SHA-256-Werte vor/nach dem Messlauf und identische Serial-/Baseline-/Bio-RGBA-, Resolved- und Depthpuffer. Der finale Release-Build enthält **keine Compilerdiagnostik**. Die Zeitfelder messen den bereits gepackten nativen Frame; GLB-Decode/Offline-Pack und Konstruktion/Mipaufbau sind getrennt im Receipt dokumentiert.

**Leistungsgrenze:** Das korrekte Textur-/PBR-Profil ist noch keine 60-FPS-Pipeline. Alle `animated4`- und `arena6`-Messframes überschreiten das 16,7-ms-Budget; nur `static2` bleibt in diesem Hostlauf darunter. Die Messungen sind eine Sandbox-Beobachtung und keine geräteunabhängige FPS-Zusage.

## Validierung und Reproduktion

- Vollsuite: `python -m unittest discover -s software_gpu/tests -p 'test_*.py' -v` → **293 Tests, 2 übersprungen, OK**, 116,561 s.
- Native Materialoracles: perspektivkorrekte (nicht affine) UV-Interpolation, sRGB-Filterung/Repeat/Mipbildung und Cook-Torrance-/Normalmap-Stützpunkte.
- Import-/Integrationsoracles: echtes eingebettetes PNG-Fixture; nichtleere, vielfältige PBR-Pixel; Serial-/Baseline-/Bio-Vollpufferparität; URI-Textur- und Texture-Transform-Ablehnung.
- Skinning-Normalenoracle: nichtuniformer und geschert gewichteter Skinmatrixmix, native inverse-transponierte Transformation gegen NumPy.
- Reproduzierbarer Originalmodellbenchmark und NPZ-Frames: [`evidence/native-pbr-20261013-fixed/benchmark/`](../evidence/native-pbr-20261013-fixed/benchmark/); das vollständige Testprotokoll liegt daneben unter [`full-suite.log`](../evidence/native-pbr-20261013-fixed/full-suite.log).
- Vollständiges Testprotokoll: [`full-suite.log`](../evidence/native-pbr-20261013/full-suite.log). Visuelle Arena-Stichprobe: [`original-arena-smoke.png`](../evidence/native-pbr-20261013/original-arena-smoke.png).
- Original-GLB-Prüfsummen passen weiterhin zum versionierten Modellmanifest; Originalbinaries und native Benchmarkexecutable sind nicht in Git eingecheckt.

Lokale Reproduktion (nach Bereitstellen der Originaldateien mit den vom Manifest geforderten Dateinamen):

```sh
python tools/install_reference_arena_assets.py /pfad/SoftwareGPU_Referenzarena_GLB_Modelle.zip
python tools/benchmark_models.py \
  --assets /pfad/zu/den/Originaldateien \
  --output-dir /tmp/native-pbr-arena \
  --phase bench --projection perspective --render-profile pbr \
  --cases animated4,static2,arena6 --repeats 15 --seconds 600
python -m unittest discover -s software_gpu/tests -p 'test_*.py' -v
```

Für große PBR-Szenen kann die Bio-Lane explizit auf die räumliche
`locality`-Policy gestellt werden. Sie behält dieselbe vorbereitete Geometrie,
dieselben Worker und vollständige Pufferparität bei, vermeidet aber die in
`animated4` teurere Frontier-/Checkpoint-Orchestrierung:

```sh
python tools/benchmark_models.py ... --bio-policy locality
```

## Bewusste Grenzen / nächste Schritte

Nicht enthalten sind Hardware-GPU-Ausführung, alpha blending/masking, mehrere GLB-Primitives, zusätzliche UV-Sets, beliebige glTF-Erweiterungen/Transforms, HDR-IBL, Schatten, Morph Targets, pixelgleiche Three.js-Reproduktion sowie eine 60-FPS-Leistungsfreigabe. Der nächste Schritt ist Profiler-getriebene Optimierung bei unveränderter Vollpufferparität; zusätzliche Materialfeatures benötigen jeweils einen expliziten, versionierten Vertrag und eigene Fixtures/Oracles.

## Aktualisierung 2026-10-13: Bio-Lane locality optimization

Ein kontrollierter 15-Paar-Lauf mit identischem Source-Stand und identischer
`animated4`-Szene verglich `combined` und die vorhandene `locality`-Policy. Die
`locality`-Lane nutzt weiterhin den Bio-Scheduler und räumliches Tile-Binning,
vermeidet aber Frontier-, Checkpoint- und Resident-Worker-Overhead für diesen
großen Workload. Die Ausgabe bleibt vollständig identisch.

| Policy | Bio Median / p95 / Max (ms) | Median-Speedup zur Baseline | Full-buffer parity |
|---|---:|---:|:---:|
| `combined` (Kontrolle) | 60,631 / 67,230 / 75,941 | 1,627× | `true` |
| `locality` (optimierte Lane) | 56,058 / 60,473 / 63,919 | 1,633× | `true` |

Das entspricht im selben Hostlauf **7,5 % weniger medianer Bio-Wandzeit**.
Zusätzliche Regressionen auf `static2` und `arena6` blieben ebenfalls bei
`full_buffer_parity=true`; ihre locality-Mediane betrugen 11,884 ms bzw.
58,103 ms. Die neue CLI-Option ist opt-in; der bisherige `combined`-Default
bleibt unverändert. Receipts und Frame-Arrays liegen unter
`evidence/native-pbr-20261013-locality/` und der Combined-Kontrolllauf unter
`evidence/native-pbr-20261013-combined-control/`.
