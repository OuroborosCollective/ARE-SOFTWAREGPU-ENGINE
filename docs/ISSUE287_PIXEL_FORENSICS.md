# CPU Pixel Forensics (#287): SHA-gebunden, opt-in, keine Game-Authority

## Verwendung

Die Forensik wird ausschließlich explizit über den echten CPU-Tiles-Renderer aufgerufen:

```python
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.pixel_trace import PixelForensicTrace, inspect_trace_receipt

fb = Framebuffer(64, 64)
raster = SoftwareRasterizer(fb, backend="tiles", num_threads=1)
trace = PixelForensicTrace(fb, x=32, y=32,
                           source_revision="40-character-actual-git-head",
                           max_events=32)
try:
    raster.draw_mesh_traced(vertices, faces, shader, trace)
    receipt = trace.finish()
    print(inspect_trace_receipt(receipt))
finally:
    raster.executor.shutdown(wait=True)
```

Die volle Quellrevision muss der Aufrufer selbst aus Git beziehen. Der String im
Beispiel ist ein ungültiger Platzhalter und wird bewusst abgelehnt.
`declared_repository_revision` ist **nur deklariert**, nicht unabhängig
verifiziert (`revision_verified: false`). Zusätzlich werden die
tatsächlich gelesenen vier Implementierungsdateien
`pixel_trace.py`, `rasterizer.py`, `tile_backend.py`,
`geometry.py` jeweils mit SHA-256 gebunden. Der
`receipt_sha256` ist SHA-256 über kanonisches JSON ohne das Digest-Feld.
Ein externer Git-Readback muss die deklarierte Revision und diese Quellen gegen
den Checkout abgleichen, bevor eine Git-SHA-Identität bestätigt ist.

## Daten und Kausalitätskette

- `draws` enthält die tatsächlich übergebenen, geordneten Draws mit
  Input-Primitive-Anzahl, erzeugten Rasterdreiecken und SHA-256 der Eingabe.
  `draw_sequence_sha256` bindet diese geordnete Übersicht.
- `source_faces` ist eine **opt-in** Sidecar-Abbildung: Ein ursprünglich
  eingereichtes Dreieck kann durch Near-Plane-Clipping mehrere
  `raster_triangle_id`-Einträge mit eigener `clip_piece` haben.
- Für das ausgewählte Pixel werden die tatsächlichen Edge-Float32-Bits, der
  Top-left-Kantentest, striktes Depth-`<` und echte Shader-Calls
  aufgezeichnet. `final_owner` ist das zuletzt tatsächlich schreibende
  Fragment, kein vorausberechneter Kandidat.
- `final_rgba`, `final_depth_f32_bits` und SHA-256 der **gesamten**
  RGBA-/Float32-Depth-Framebuffer sind eigene deterministische Ausgaben.
- Kein Alpha-Blending: Auch ein Fragment mit Alpha 0 speichert Farbe und
  Tiefe. Bei Equal-Depth gewinnt der frühere Draw. Ungültige NaN-Varyings
  und -Positionen werden vom gemeinsamen Geometry-Stage verworfen.
- Maximal **256** Events, maximal **32** Draws, begrenzte Face-/Vertex-Anzahl.
  Nach Shader-Ausnahme ist das Receipt unvollständig und `finish()`
  verboten. Nach `finish()` sind weitere Draws unzulässig.
  Keine fremden URI-Zugriffe, kein Netz, kein Upload, keine Roh-Texturpersistenz.
- Nur `backend="tiles"`, ohne adaptive Lernroute, Cache, Numba-JIT,
  plan/batch, deferred oder native C++. Kein impliziter Paritätsbeweis für
  andere Backends oder MSAA.
- `inspect_trace_receipt()` verifiziert Quota, Format, SHA256 und
  erzeugt eine reine Markdown-Analyseansicht ohne Aurion-Spielautorität,
  Datenbank-, GPU- oder Trainingszugriff.
- Der normale `draw_mesh()`-Pfad erzeugt kein Trace-Objekt, keinen
  zweiten Raster-Durchgang und keinen zusätzlichen Shader-Call. Die
  opt-in Funktion verändert nicht die Raster- oder Floating-Point-Formel.

## Abnahme und Einschränkungen

`python -m unittest software_gpu.tests.test_pixel_forensic_trace -v`

Echte Raster-Regressionen prüfen: überlappende/equal-depth/nähere
Dreiecke, Mehrdraw-Reihenfolge, Near-Clip-Fan, NaN-Verwerfen, alpha=0,
vollständige Byte-Parität von RGBA8 und Float32-Tiefe sowie echte
Fragment-Call-Anzahl; falsches Pixel, Budget/SHA, Tamper, Backend,
zusätzliche Draws nach `finish()` und Shader-Ausnahme.
Die Testserie wird in `evidence/test-series-catalog-v1.json` registriert
und im CPU-Ranglistendokument neueste zuerst geführt, **ohne**
zeitbasierte Performance-Rangfolge. Kein neuer Speedup, keine Hardware-GPU
und keine aktuelle Aurion-Runtime werden behauptet.
