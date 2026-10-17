# CPU-Shader-Hotpaths: drei getrennte Optimierungen (17. Oktober 2026)

**Status:** Source-bound CPU-Funktionsmessungen in [PR #113](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/pull/113). Dies ist **kein** Nachweis für eine generelle FPS-Steigerung, eine Hardware-GPU, AREMDL03-PBR oder Aurion.

## Messwerte auf dem GitHub-Runner

| Getestete Änderung | Original → optimiert | Median des gepaarten Speedup | Kandidat schneller |
| --- | --- | ---: | ---: |
| VertexColor-**Skalar**funktion | `np.clip(...).astype(uint8)` → NumPy-Skalar-RGB-Fastpath, NaN-Fallback | **2,7981×** | **15/15** Paare |
| Blinn-Phong-**Kanal-Clamping** | `math.isnan` + `min/max` → Inline-Vergleich mit NaN-Fehler | **2,3841×** | **15/15** Paare |
| VertexColor-**Batch**funktion | temporäres Multiply+Clip+RGB-Array → In-Place-Clip eines eigenen RGB-Buffers | **1,1500×** | **13/15** Paare |

**Primärbeleg:** [GitHub Actions – 15-Paar-Shader-Hotpath-Research](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/39049231969), Code-Head `5fc07f825502b1bb135106e022fd5098bacb6f55`, Receipt-SHA256 `3662da05f1d2131547b832bdb97fbd2813648ce7e866980271d26f7a25eca12c`.

**Umgebung:** Linux GitHub-hosted Ubuntu 24.04, Python 3.12.15, NumPy 2.5.4, seriell auf einem CPU-Runner; 15 abwechselnde Original-/Kandidaten-Paare. Die JSON-Receipt-Datei im CI-Artefakt enthält Einzelzeiten, IQR, MAD, Python-/NumPy-Version, Host und Quellcode-SHA256; der CI-Job prüft diese und seinen eigenen Digest erneut.

## Numerischer Geltungsbereich und Regressionen

- **Blinn-Phong:** Reines Kanal-Clamping wurde für eine identische vorliegende Float-Eingabe verglichen; `NaN` muss weiterhin mit `ValueError` abbrechen, ±Infinity sättigt unverändert. Der funktionale Gewinn ist **kein** End-to-End-Fragment-/Frame-Faktor.
- **VertexColor scalar:** Gemessen wurde die tatsächlich aufgerufene `fragment_shader`-Methode gegenüber der vorherigen NumPy-Fassung. Float32/Float64-Farbdreier verwenden die identische NumPy-Skalar-Multiplikation, alle anderen Typen und NaNs verwenden die ursprüngliche NumPy-Konvertierung. Grenzwerte um `k/255` wurden separat geprüft.
- **VertexColor batch:** Gemessen wurde die vollständige `fragment_shader_batch`-Methode gegenüber der vorherigen Version. Der Eingangspuffer wird nicht verändert; ungültige Form und nichtfinite Batcheingaben bleiben gesperrt; die Ausgabearrays bleiben RGBA8. Array-Allokationszahl wurde aus dem Codevergleich hergeleitet, **nicht** als separate Peak-Memory-Messung zertifiziert.
- Die spezialisierte CI hat **9 neue numerische/Framebuffer-Tests** sowie **8 bestehende Blinn-Phong-Tests** erfolgreich abgeschlossen, einschließlich realer RGBA- und Float32-Depth-Parität. Die vollständige Repository-CI ist zusätzlich erforderlich, bevor eine Integration nach `main` als erfolgreich gilt.

## Reproduktion

```bash
python -m unittest software_gpu.tests.test_shader_clamp_optimizations -v
python -m unittest software_gpu.tests.test_shader_half_vector_cache -v
python -m software_gpu.benchmarks.compare_shader_hotpaths \
  --output /tmp/shader-hotpath-report.json --repeats 15
```

Keine Runtime-Fakes, keine GPU-, Cloud-Training- oder Shader-Modelländerungen. Die Werte stammen aus echten CPU-Funktionsausführungen, nicht aus einer Modellschätzung. Der Run `39049231969` gilt **nur für den dort genannten Head**; spätere Head- und Post-Merge-Ergebnisse sind separat zu lesen.
