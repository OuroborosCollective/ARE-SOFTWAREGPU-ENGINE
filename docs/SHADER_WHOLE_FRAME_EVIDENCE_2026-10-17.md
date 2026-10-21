# Whole-frame CPU-Shader-Impact: geprüfte A/B-Messung (2026-10-19)

**Vergleich:** #113 wurde auf `main` als Commit `711daab6e6930374a2a8be1d0864f4bb87c63d59` integriert. Dieser Forschungs-PR vergleicht den explizit rekonstruierten vorherigen `VertexColorShader` mit dessen aktueller Implementierung innerhalb eines realen `draw_mesh`-Aufrufs. Er misst **nicht** die anderen Shader aus #113 (etwa Blinn-Phong), keine komplette Spiel-Frame-Pipeline mit Clear/Present/Animation und keine Hardware-GPU. Keine Änderung der Produktions-Backend-Policy.

## Unveränderlicher historischer CI-Beleg für die ursprüngliche Forschungsrevision

- [GitHub Actions 39053027612](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/39053027612), PR-Head `9c3026d1fd6d3503bb08b464feda849fd9e1ceb1`.
- Artifact ID **12108431228**, Name `shader-whole-frame-67bac970cd88a78bf701726258922b389d8eb0cf`, ZIP-SHA-256 `530044190e077e9acdb7ff671fe4e7a800af4e866c3c2a22d1bcf606e8b1eb4a`, CRC PASS.
- `report.json` SHA-256 gemäß kanonischem JSON-Body `98bc71dafbdb42b822039a5ea97661c165ae3ae41c624ee060f5504540b5083f`; die sechs in der Datei deklarierten Source-SHA-256 wurden im ursprünglichen CI gegen den Checkout geprüft.
- 96 x 96 Pixel; 2 Worker; 15 alternierende, gemessene AB/BA-Paare je Fall; ein Aufwärmpaar; Zeitmessung umfasst `draw_mesh`, nicht `clear`, Hashing oder Renderer-Initialisierung. Original-Runner Linux 6.17.0-1022-azure / Python 3.12.15 / NumPy 2.5.4 (4 logische CPUs).
- Jeder gemessene Draw zeigt vorher/nachher denselben RGBA8- und float32-Tiefenbuffer-Hash; Scalar- und Batch-Ausführung liefern je Szene ebenfalls dieselben Puffer. Byteidentität gilt nur für die geprüften Szenen, Auflösungen und Rasterpfade.

| Geometrie / Ausführung | Vorher Median ms | Vorher IQR / MAD ms | Nachher Median ms | Nachher IQR / MAD ms | Median der 15 Paar-Ratios | Nachher schneller |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 8 große Dreiecke / tiles-scalar | 110.716 | 8.780 / 2.029 | 64.227 | 9.059 / 4.814 | **1.7169x** | 15/15 |
| 8 große Dreiecke / plan-batch | 31.477 | 6.801 / 1.909 | 29.347 | 0.199 / 0.098 | **1.0639x** | 14/15 |
| 160 kleine Dreiecke / tiles-scalar | 41.844 | 2.332 / 1.442 | 34.409 | 5.617 / 1.834 | **1.2069x** | 13/15 |
| 160 kleine Dreiecke / plan-batch | 36.838 | 1.537 / 0.764 | 36.604 | 6.352 / 1.887 | **0.9738x** | 6/15 |

IQR = linear interpoliertes 75%- minus 25%-Quantil der 15 Einzelzeiten; MAD = nicht skalierter Median der absoluten Abweichungen vom Einzelzeit-Median. **Die Ratio ist der Median der 15 einzeln gepaarten Quotienten**, nicht der Quotient der beiden angezeigten Mediane. Alle diese Streuungswerte wurden aus dem Original-Artifact unabhängig berechnet. Die signifikant schwankenden Host-Laufzeiten und vier getesteten Konfigurationen erlauben weder universelle FPS-Garantien noch automatische Backend-Umschaltung. In `small-triangles/plan-batch` ist ein Vorteil **nicht nachgewiesen**; die gemessene Ratio ist sogar kleiner als 1.

## Receipt-Gate und Grenzen

Die ursprüngliche Implementierung von `validate()` prüfte keine Commit-Identität, Quellhashes, Szenenmetadaten, Einzelmediane oder Streuung. Die ursprüngliche Evidence-Datei referenzierte außerdem den noch älteren Run 39052922640 mit widersprechenden Batch-Ratios. Beide Befunde wurden im Review als **P1** eingeordnet. Der bestehende Draft #115 enthält daher verschärfte Validierung und negative Regressionen, unter anderem für selbst neu signierte, verfälschte Reports. Das historische Artifact wird **nicht** rückwirkend verändert; ein neuer Report muss auf dem **exakten neuen PR-Head** durch CI frisch erstellt, heruntergeladen und mit der aktuellen Implementierung geprüft werden.

Die Quellhashes müssen genau die sechs im Benchmark deklarierten Dateien abdecken und zu deren Checkout-Bytes passen; außerdem müssen `head_sha`, 15 positive endliche CPU-Messpaare, Alternierung, Szene/Modus, Polygonanzahl, Pixel/Worker, Puffer-Hashes, Batch-Proben und Median/IQR/MAD zusammenpassen. Ein selbstsignierter Digest ersetzt keine externe Commit-/Quellprüfung. Die vier Fälle wurden absichtlich mit `batch_min_samples=1` gemessen: Das ist eine **Benchmark-Ablation** und keine Änderung der produktiven Policy. Peak-RSS, Energie, VRAM und tatsächliche Spiel-FPS wurden **nicht** gemessen.

**Final-Head-Abnahme:** [PR #115](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/pull/115) bleibt Draft, bis der neue Head durch alle benötigten Jobs bestätigt wurde, der neue SHA-gebundene Artifact-Readback mit seinen tatsächlichen Messwerten separat dokumentiert ist und unabhängige Review/Approval vorliegt. Diese historische Tabelle ist kein Ersatz für die Final-Head-Messung und rechtfertigt keine Produktivstrategie-Änderung.

Reproduktionsbefehle im vollständigen Checkout:

```bash
python -m unittest software_gpu.tests.test_shader_frames -v
python -m software_gpu.benchmarks.compare_shader_frames --output /tmp/frame-report.json --pixels 96 --workers 2
```
