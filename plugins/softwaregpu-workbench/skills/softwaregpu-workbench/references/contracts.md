# Raster- und Evidence-Verträge

Farben und Tiefe getrennt sowie kombiniert prüfen. Top-left-Kanten, strikt kleinere Tiefe, erste Submission bei Gleichstand, perspektivische Varyings, Near-Plane-Clipping, Sliver, degenerierte und nichtfinite Primitive prüfen. Float32-Auswertungsreihenfolge erhalten; inkrementelle Edge-Updates oder FMA brauchen einen neuen numerischen Vertrag und Differentialtests.

Batch-Shading nur bei explizit gebundener Scalar-Äquivalenz verwenden. Ein Scalar-Sample verursacht hier einen tatsächlichen Aufruf; `scalar_fragment_calls` ist daher eine Aufrufzahl. Batch-Aufrufe und Batch-Samples separat führen. `shaded_samples` ist Arbeitsmenge einschließlich Overdraw, keine Anzahl endgültig sichtbarer Pixel. Arbiträre zustandsbehaftete Shader nicht über Dreiecksgrenzen bündeln; Depth und Aufrufreihenfolge bewahren.

Bei vollständigen geplanten Draws:

```
binned_pairs = inside + outside + boundary + scan_bypassed
small_pairs = scan_bypassed
shaded_samples = batch_fragment_samples + scalar_fragment_calls
```

Bei `counts: null` keine Ausführungs-Counter erfinden. Vorabmerkmale unabhängig prüfen. Inside-Kacheln benötigen weiterhin dichte Barycentrics/Tiefe. Receipt-Digests aus dem vollständigen kanonischen JSON-Body ohne Digest berechnen. Unbekannte additive Felder erhalten. Provider-/Gameplay-Authority nicht aus Graphfarben ableiten.

Vier Ablationen mit identischen Shader-Funktionen und vergleichbarem Instrumentierungsumfang messen: kein Scan/scalar, kein Scan/batch, Scan/scalar, Scan/batch. Draw-Gate für alle vier deaktivieren und tatsächliche Policy-Werte im Receipt prüfen. Fixtures nutzen Seed 1234; prozedurale Referenzen Seed 991. CPU-Modell, Affinity, Python-/NumPy-Build, Thread-Umgebung, Wiederholungen, Rohzeiten, IQR/MAD und Code-SHA speichern. 15 Wiederholungen sind ein Ausgangspunkt, keine Zuverlässigkeitsgarantie.

Wolfram ausschließlich als unabhängiges Mathematik-Orakel behandeln: `software_gpu/evidence/wolfram-surface-plan.v1.wl` gegen das exakte JSON und das reale Float32-Verhalten prüfen. Exakte algebraische Äquivalenz garantiert keine Byte-Identität auf Float32. Keine GPU-Parität aus CPU-vs.-CPU-Ratios ableiten.
