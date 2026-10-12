# Implementierungsplan: perspektivisch korrekte GLB-Texturen und PBR im nativen C++-Pfad

**Stand:** 2026-10-12
**Ausgangspunkt:** `main`-basierter Referenzarena-/Frame-Timing-Branch; derzeitiger GLB-Rendervertrag `AREMDL01` / `are.model-input.v1`.

Zum gemessenen Ausgangspunkt und zu den archivierten Arenareferenzen siehe den
[Referenzarena-/Timing-Handoff](reference-arena-handoff-20261012.md).

## Zielbild

Die bestehende Offline-GLB-Vorbereitung soll originale Materialien/Texturen in ein begrenztes, validiertes Szenenpaket überführen. Der **gesamte pro-Frame-Pose-, Clip-, Interpolations-, Textursampling-, Beleuchtungs- und Rasterpfad bleibt nativ in C++**. Der C++-Rasterpfad rendert eine explizite Perspektivkamera mit Near-/Far-Clipping und perspektivisch korrekter Interpolation von UV, Normalen und weiteren Shading-Attributen. Baseline und Bio-Scheduler erhalten dasselbe Szenenpaket und dieselben Operationen.

Der bisherige 64-Dreiecks-/`ARERIN01`-Wire-Vertrag, `AREMDL01`, die Diagnosebeleuchtung und die bestehenden VertexColor-/Rastertests bleiben rückwärtskompatibel. Die neue Materialpipeline wird ausschließlich über ein versioniertes, separates Modellprofil freigeschaltet. Es gibt keinen stillen Verhaltenswechsel der Alt-ABI.

**Nicht das v1-Ziel:** beliebige glTF-Erweiterungen, Transparenz/Blending, Alpha-Masken, morph targets, mehrere Primitive pro GLB, Shadowmapping, Screen-space reflections, HDR-IBL oder eine pixelgleiche Reproduktion von Three.js. Diese Eigenschaften erhalten später explizite Verträge.

## Was im Bestand tatsächlich vorliegt

Der Pfad heute ist `model_probe.py` (GLB parsen und `AREMDL01` packen) → `model_scene.hpp` (Pose, Skinning, orthografisch normalisierte/gefitte Dreiecke und Diagnosefarbe) → `workrooms.hpp` (`Vertex{x,y,z,w}`, vorbereitete Fläche, flat RGBA, Raster, Depth, MSAA und AA) → unveränderte Rendereroperationen im `BioPipeline`.

`model_scene.hpp::frame()` schreibt native GLB-Positionen zurzeit mit `w = 1` in den Clipdatensatz; `workrooms.hpp::render()` teilt `x/y/z` durch `w`, rastert aber ausschließlich `rgba`. Es gibt dort weder UV- noch interpolierte Normalenattribute, Texturspeicher, Sampler oder Materialindex. `Scene::fit()` erzeugt einen festen orthografischen Fit. Der Modellpfad prüft vorhandene Materials nur auf `OPAQUE`/doppelseitig und ignoriert PBR-Werte und Bilder.

Inventur der sechs verifizierten Referenz-GLBs:

| Modelle | `POSITION` | `NORMAL` | `TEXCOORD_0` | `TANGENT` | Materialbilder |
|---|---:|---:|---:|---:|---|
| Magier, Assassinin, Axt-, Schwertkämpfer | vorhanden | vorhanden | vorhanden | **fehlt** | je GLB 3 eingebettete PNGs: Base Color, Normal Map und Metallic-Roughness |
| Baumstamm, Felsen | vorhanden | vorhanden | vorhanden | **fehlt** | je GLB 1 eingebettetes JPEG: Base Color |

Alle sechs sind einzelne indizierte Primitive, undurchsichtig und doppelseitig; die Figuren verwenden glTF-Standard-Samplers (min `LINEAR_MIPMAP_LINEAR`, mag `LINEAR`, Wrap-Defaults `REPEAT`). Die zwei Umfeldmaterialien haben `metallicFactor=0`, `roughnessFactor=0.8`; ihre Textur ist die Base Color. Die Zeichen-Materialien referenzieren alle drei Kernmaps. Da keines `TANGENT` enthält, muss Normal-Mapping auch ohne exportiertes Tangentenattribut funktionieren.

## Reihenfolge der Arbeitspakete

### 0. Vertrag einfrieren, Fixtures und Referenz definieren

**Zweck:** Erst einen eindeutigen numerischen/Materialvertrag festlegen, ehe C++- und Importeränderungen auseinanderlaufen.

- GLB v2-Core-Subset samt erlaubten/accessor-gesperrten Attributen, Materials, Images, Textures und Samplern spezifizieren.
- Definieren: Rechtshändigkeit, View-/Clip-Konvention, NDC- und Depthbereich, Pixelzentrum und MSAA-Samplepositionen, glTF-UV-Konvention, sRGB-/Linear-Konvertierung, Tie-Break-/Top-left-Regel und Fehlertoleranzen.
- Eine kleine Fixture erzeugen: zwei überlappende Dreiecke, UV-Seam/Mirrors, bekannte 2×2 sRGB-Basecolor, Normal Map, Metallic-Roughness-Map, bilineare und Repeat-Abtastung, ein Dreieck über der Near Plane und ein perspektivischer Test, in dem affine UV-Interpolation nachweislich falsch ist.
- Eine von `workrooms.hpp` unabhängige Python-/NumPy-Referenz für Clip-Schnitt, baryzentrische Perspektivkorrektur, Textursample und ausgewählte PBR-Stützpunkte einrichten. Keine Renderpixel in derselben C++-Implementierung als eigene Oracle verwenden.

**Abnahme:** Testvektoren für Projection, Clipping, UV, sRGB und Materialfaktoren sind reviewbar und deterministisch, bevor v1 Shading entwickelt wird.

### 1. Separaten Perspektiv-/Clip-Geometrievertrag einführen

**Primärdateien:** `native/symbolic/model_scene.hpp`, `native/symbolic/workrooms.hpp`, bei getrenntem Profil ein neues `native/symbolic/model_render.hpp` und/oder ein weiteres eng begrenztes Model-Wireformat.

- Explizites Kamerasetup (View-/Projection-Matrix oder Kamera-Pose, vertikales FOV, Aspect, Near, Far) einführen. Für den Benchmark ist die Referenzarenakamera fest und hashbar; keine implizite „fit über jeden Zeitstempel“-Kamera im Perspektivmodus.
- View-Space nach homogenem Clip-Space transformieren; Clipkoordinaten behalten, bis Rastersetup `1/w`, NDC-Tiefe und Bildschirmpunkte berechnet.
- Dreiecke vor dem Divide gegen die sechs Clip-Halbräume schneiden. Position **und jedes per-Vertex-Attribut** werden an Clip-Kanten linear interpoliert; das entstehende Polygon wird deterministisch mit fester Windungsregel trianguliert.
- Clipping kann aus einem Eingangsdreieck eine variable Anzahl Ausgabedreiecke machen. Das Model-Profil braucht deswegen einen separaten, vor dem Worker-Dispatch festgeschriebenen Frame-Packetvertrag mit Obergrenze/Overflow-Reject sowie passenden State-/Prepared-/Bin-Puffern. `BioPipeline` muss seine per-Primitive Strukturen für dieses Modellprofil vor Ausführung konsistent an den neuen Packetumfang anpassen; während eines laufenden Frames wird nie umallokiert.
- Maximale Clipping-Expansion, Near-Plane-`w`-Grenze, degenerate Polygone, NaNs/Infs und Dreieckslimits explizit begrenzen. Keine stillen Weglassungen oder inkorrekten Vertex-Projektionen.
- Die bestehende Orthographic-/Diagnose- und Legacy-ABI unverändert lassen; das alte Profil muss dieselben Referenzpuffer behalten.

**Abnahme:** analytische Projektion, Near-/Far-/Side-Clipping, Kamera-Frustum-Cases, rückwärts liegendes `w`, degenerierte Polygone, Shared Edges und Submission-Ties bestehen Baseline- und Bio-Paritätstests.

### 2. Bounded glTF-Material-/Bilddaten im Offline-Importer erschließen

**Primärdatei:** `software_gpu/research/model_probe.py`; ein neues Payloadschema wie `AREMDL02` wird unabhängig von `ARERIN01`/`AREMDL01` versioniert und abgelehnt, wenn magic/version nicht exakt erkannt wird.

- `TEXCOORD_0`, `NORMAL` und bei Vorhandensein `TANGENT` aus validierten glTF-Accessors lesen; Attributform, Komponenten, Stride, Alignment, Normalization und Zahlenbereich prüfen. Material-/Texture-/Image-/Sampler-Indizes streng gegen Listenlängen validieren.
- Nur die im GLB-eigenen BIN-Chunk eingebetteten PNG/JPEG-Bilder zulassen. Keine externen URI-Fetches. MIME gegen tatsächliches Format prüfen; CRC-/Trunkierungs-/Dimensionstests auf Decoderpfad legen.
- PNG/JPEG **offline** zu begrenzten RGBA-Pixeln dekodieren (z. B. vorhandene Pillow-Abhängigkeit, sonst bewusst eingeführte und getestete Importerabhängigkeit). Farbtextur und lineare Datentexturen bleiben mit expliziter Farbraumkennung auseinandergehalten.
- Materialdatensatz für glTF-Core-`metallicRoughness` transportieren: `baseColorFactor`, Base-Color-Texture, `metallicFactor`, `roughnessFactor`, Metallic-Roughness-Texture, `normalTexture`/Scale, optional `emissiveFactor`/Texture und `occlusionTexture`/Strength mit korrekten Defaults. `TEXCOORD_0` ist die im Kern unterstützte UV-Semantik. Samplerfilter und Wrapmodi werden explizit repräsentiert.
- Für v1 erlaubte Primitive/Materialkombinationen klar beschränken: ein Material pro Indexdreieck-Primitive, `OPAQUE`, doppelseitig, ein UV-Set. Alpha-Mask/Blend, Skin-Extension-, Draco-, KHR_texture_transform und URI-Texturen fail-closed ablehnen statt still falsch zu rendern.
- Vor Allokation Dimensionen, Kanalzahl, Map-Anzahl, Multiplikationen und Gesamt-Bytes/Pixelbudget prüfen. Budget für dekodierte Daten muss Szene, Stagingkopien, Mips und Multiworker-Scratch zusammen einschließen; vor C++-Build messbar und dokumentiert.

**Abnahme:** kaputte Offsets, ungültige Accessors, Bild-Decoderfehler, unbekannte Extensions, fremde Materialindizes, fehlende UVs für referenzierte Maps, übergroße/overflowende Mips und Protokoll-Trunkierung werden deterministisch abgelehnt; alle sechs Originale importieren vollständig.

### 3. Perspektivkorrektes Attributraster und Texture-Sampler ergänzen

**Primärdateien:** `native/symbolic/workrooms.hpp` oder modellspezifisches Rendererheader; `native/symbolic/bio_workrooms.hpp` bleibt beim selben nativen Renderkern.

- Einen Model-Surface-Typ einführen, dessen Bildschirm-/Depthdaten, `1/w`, `uv/w`, `normal/w`, ggf. tangent/sign-over-w, vertex color und Materialindex im Render-Setup präpariert werden. Den alten Flat-`Triangle{Vertex,rgba}`-Vertrag nicht unbemerkt erweitern.
- In derselben Top-left-Abdeckung und an derselben MSAA-Sampleposition zuerst Screen-Baryzentrika berechnen. Für jedes attribut `a` interpolieren als
  `a = (Σ λᵢ · aᵢ/wᵢ) / (Σ λᵢ · 1/wᵢ)`.
  Window-Depth gesondert gemäß festgelegter Clipkonvention linear über Z/W mit korrektem Depth-Mapping bilden; Z nicht versehentlich noch einmal mit derselben Attributformel perspektivisch interpolieren.
- Sampler deterministisch ergänzen: `REPEAT`, `CLAMP_TO_EDGE`, `MIRRORED_REPEAT`; nearest/linear Filter und Mip-Auswahl; UV-/Texture-Footprint und minification. Für glTF-Samplerdefaults eine gespeicherte, gegen Fixtures geprüfte Zuordnung implementieren. Trilineare Filterung braucht reproduzierbare Mips/LOD; Mips farbkorrekt für sRGB-Maps und datenbewahrend für Normal-/Metallic-Roughness-Maps erzeugen.
- Base-Color-Map in sRGB dekodieren, Data Maps linear behandeln, RGB/Alpha und glTF-Materialfaktoren an der definierten Stelle multiplizieren. UV-Seams, Repeat bei negativen UVs, Randfilter, perspektivisch verzerrte Checkerboards, fast-edge-on Dreiecke und 4×MSAA-Samples abdecken.
- Wenn glTF-Tangent vorhanden ist: orthogonale Tangent-/Bitangentbasis zusammen mit Normalen korrekt transformieren. Fehlt es – wie bei allen sechs Zielmodellen –, pro Fragment eine stabile Tangentbasis aus Positions-/UV-Ableitungen bestimmen. UV-degenerierte Normalmap-Flächen fail-closed ablehnen oder nach dokumentierter Regel auf geometrische Normale zurückfallen; nie undefinierte NaNs sampeln.

**Abnahme:** Das perspektivische Checkerboard stimmt sampleweise mit der unabhängigen Attributoracle innerhalb festgelegter Floattoleranz überein; ein Test demonstriert klar die Abweichung zur absichtlich falschen affinen Interpolation. Texture colors/indices und MSAA werden über Workers/Scheduler bit- oder definitionsgemäß gleich bestätigt.

### 4. glTF-metallic-roughness PBR und Linearpfad integrieren

**Primärort:** eigenständige, scalar-/unit-testbare C++-Material/Shadingfunktion, die `render`/Materialauswertung aus dem Tile-Raster aufruft.

- Beleuchtung mit festgelegter Arenakonfiguration zuerst ohne Environment-Map implementieren: energy-conserving Cook-Torrance/GGX, Schlick-Fresnel, metallic/roughness Workflow, diffuse/specular Terms, normal-map-Scale, Emissive- und Occlusion-Faktoren, doppelseitige Normalenorientierung und korrekte Normalisierung nach Skinning/non-uniform transforms.
- Alle sechs Testassets haben keine Tangenten; das priorisierte Ableitungs-TBN ist daher ein echter PBR-Featurepfad, kein späterer Cleanup.
- Kameralichtkonfiguration, Lichtintensitäten, Richtungen/Farben, Ambientapproximation, Exposure, Tone Mapping und Ausgabefarbraum festschreiben. Keinen „Three.js-identischen PBR“-Anspruch ohne dieselbe Licht-/Environment-/Tone-Mapping-Konfiguration stellen. IBL, Shadows und andere Rendererfeatures bleiben sichtbar außerhalb des MVP.
- Shading in linearem Arbeitsfarbraum ausführen. Für das neue Modellprofil linearen Sample-/Resolve-Pfad festlegen: MSAA mittelt lineare Samplefarben; Tone Mapping und sRGB-Encoding geschehen an definierter, einmaliger Stelle. Bestehenden integer-RGBA/MSAA-/FXAA-Altpfad nicht still ändern. FXAA-Eingabe/Luma-Farbraum ebenfalls im Vertrag festschreiben.
- Samplebasierte PBR-Kosten offen messen; ggf. Basecolor-/MR-/Normalmap-Komponenten zunächst mit einstellbaren Flags zur Diagnose isolieren, nicht Materials durch konstantes VertexColor ersetzen.

**Abnahme:** deterministische Stützpunkte für Dielektrika/Metalle, Rauheitsgrenzen, Fresnel, Normalmapneutralwert, doppelseitige Rückseiten, Skinning-Normalen und Farbraum bestehen unabhängige C++-/Python-Oracles. Szenen bleiben endlich und depth-stabil.

### 5. Arena integrieren, baselines sichern und leistungsgesteuert ausrollen

**Primärdateien:** `tools/benchmark_models.py`, `software_gpu/tests/test_model_probe.py` plus neue glTF-/Render-/PBR-Testmodule, `docs/native-model-benchmark.md` und versionierte `evidence/`-Receipts.

- Die laufende `animated4`, `static2`, `arena6`-Case-Aufteilung beibehalten. Im Perspektivprofil wird eine identische deklarierte Kamera und dasselbe zeit-/clipgebundene Szenenpaket an seriale Oracle, native Baseline und Bio-Scheduler übergeben. Three.js dient visueller Referenz, nicht zu Timing oder exakter Cross-Renderer-Pixelgleichheit.
- Zeitfelder pro Frame neu aufteilen: Import/Decode/Pack (außerhalb), Pose/Skinning, Projektions-/Clippingvorbereitung, Material-/Mip-Vorbereitung, Handoff, Binning, UV-/Texture-Sampling, Beleuchtung, Raster, MSAA, Tone Mapping/AA und end-to-end. Bei Bio-Frontier weiter unterscheiden: geteilte überlappende Wandzeit ist nicht die Summe der Operationskosten; Workerarbeit bleibt separat.
- Je Case mindestens 15 alternierende Paare + drei Warmups, gleiche Hardware-/Worker-/Kamera-/Mip-/Shader-/Outputkonfiguration. Median, p95, Maximum, Slow Frames und 16,7-ms-Frameanteil speichern; zusätzlich kompakte 128×128-Zielmessung (historische Budgetreferenz) und 256×256 Lastmessung. 128×128 ist ein Vergleichspunkt, kein 60-FPS-Abnahmewert.
- Bild-, Depth-, Input-, Programm-, Camera-/Material-Konfigurations- und GLB-Quellhash im Receipt ablegen. Originale bleiben lokal/private; Evidence macht Referenzwerte reproduzierbar.
- Erst nach korrekter Referenz-/Paritätsgate den Default wechseln; das Diagnose-/Flat-Colorprofil bleibt für numerische Rasterregressionen und ABI-Altvertrag verfügbar.

**Abnahme:** alle sechs GLBs einschließlich der Figuren-Normalmaps und MR-Maps sichtbar in native output; statische/animierte Szenen laufen in serieller Baseline und Bio denselben frame-timed Workload; Fehlinputs brechen ohne Teilframe-Commit ab; Quellen-/Material-/Kamerahashes sind im Receipt fixiert; Performancebericht zeigt auch Ausreißer und Ladezeiten.

## Definition of Done

1. Legacy `ARERIN01`/VertexColor-Tests und der bisherige Diagnose-Modellbenchmark bestehen unverändert.
2. Das versionierte Modellprofil rendert perspektivisch mit Clip-Space-Clipping und analytisch getesteter perspektivisch korrekter `TEXCOORD_0`-Interpolation.
3. Basecolor-, Normal- und Metallic-Roughness-Maps aller sechs Originale werden mit Faktoren, Farbraum, Sampler und doppelter Seitenausrichtung korrekt ausgewertet; Umfeld-JPEGs sowie Charakter-PNGs rendern.
4. Native serial, Pipeline-Baseline und Bio erzeugen pro Sample-/Depthvertrag deterministische, exakt gleiche Framebuffer; unabhängige mathematische Oracles prüfen Perspektivattribute, Sampling und PBR-Kerne.
5. End-to-end Kosten und Phasenp95/slow frames werden berichtet. 60 FPS ist ein Folgeziel, keine v1-Freigabe, sofern Messwerte es nicht tatsächlich belegen.

## Hauptrisiken und bewusste Leitplanken

- **Near-Plane-Clipping ändert Topologie:** variable clip-geometrie benötigt einen neuen, begrenzten Model-Frame-Packetvertrag sowie Binning/Pipeline-Rebuild vor dem Scheduler; keinen Runtime-Realloc im Tile-Worker.
- **Normal Maps ohne exportierte Tangenten:** sämtliche Zielcharaktere brauchen eine stabile, testbare Ableitungsbasis; nur eine Basecolor-UV-Implementierung wäre kein erfüllter PBR-Schritt.
- **PBR- und Farbmanagement:** sRGB in linear mischen, Gamma zweimal anwenden oder MSAA in falschem Raum mitteln liefert sichtbar falsche Farben; Legacy-Bytepuffer darf kein stillschweigender Arbeitsraum für glTF-Materialien bleiben.
- **Texture-Import-Speicher/DoS:** GLB-/JPEG-/PNG-Abmessungen, Mip-Ketten und Frame-Buffer multiplizieren Speicher. Strikte Budgets müssen vor Decoder- und C++-Allokation gelten.
- **Reference drift:** Three.js und der C++-Renderer sind nur visuell über dieselbe Kamera-/Licht-/Materialvereinbarung korrelierbar. Die autoritative numerische Parität ist serial-native gegen Baseline/Bio, ergänzt um unabhängige CPU-Oracles; nicht „Screenshot sieht ähnlich“.
- **Performancekosten:** 4×-Sample-PBR samt Normalmaps kann das heutige Framebudget deutlich übersteigen. Erst ein korrektes, gut instrumentiertes Ergebnis herstellen, dann den gemessenen Kostentreiber optimieren; keine LOD-/Pixel-/Map-Reduktion, bevor sie als sichtbare Qualitätseinstellung spezifiziert und separat getestet ist.
