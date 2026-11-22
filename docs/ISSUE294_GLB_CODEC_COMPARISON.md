# Issue #294: Opt-in GLB2 Draco/Meshopt CPU-Vergleich

Geltung: Das bestehende native C++17-AREMDL03-Rendering und die
GLB-Importer-Authority bleiben unveraendert. KEIN Codec-Upgrade und
KEIN neuer CPU-Ranglisteneintrag bei fehlender Geometrie-Semantik.

Das Quellenmanifest evidence/issue294-asset-codec-sources-v1.json fixiert
Khronos-Quellcommit, SHA-256, Bytes, Lizenz-URL und LOD0-original fuer
Box, CesiumMan, DamagedHelmet (CC-BY-NC; nicht redistribuieren),
Fox und MorphPrimitivesTest. LOD1+ bleibt unverified, nie synthetisch
als Produktion behandelt. CLI @gltf-transform/cli 4.5.1 und exakte
package-lock.json sind fest gepinnt. Encoder und Decoder nutzen
denselben Build; Draco = copy; Meshopt = copy und dequantize. 


Nach privatem SHA-geprueftem Download der Originale:

    npm ci --prefix tools/asset-codec-comparison-node --ignore-scripts --no-audit --no-fund
    python -m unittest software_gpu.tests.test_asset_codec_comparison -v
    python -m software_gpu.benchmarks.asset_codec_comparison --manifest \
      evidence/issue294-asset-codec-sources-v1.json --asset-dir ASSET_DIR \
      --codec-bin tools/asset-codec-comparison-node/node_modules/.bin/gltf-transform \
      --package-lock tools/asset-codec-comparison-node/package-lock.json \
      --output /PRIVATE/issue294-receipt.json --repeats 15 --pixels 64 --workers 1

Pro tatsaechlich von ARE angenommene Codec-Variante 15 interleaved
Pipeline-Runs: SHA-Dateilesung, Dekodierung, realer PBR-Import,
Bone-/Pose-Evaluation, erster und warmer nativer CPU-RGBA8/
Float32-Depth-Frame, Freigabe und Quellen-/Renderer-Digests.
Der native Probe waermt intern dreimal auf: first_frame_ms ist
kein Cold-Start. native_wall_ms umfasst den Prozessstart. Peak RSS
ist nur das Prozess-Lebenszeit-Hochwasser der Python-Messung,
kein stage- oder Decoder-RSS; Bandbreite = Datei-Bytes/Lesezeit.
Workers 1/2/4/8 nur fuer tatsaechliche native Parallelisierung,
gemessen wird ausschliesslich die im Receipt genannte Workerzahl.

Material-/Rig-/Clip-/Morph-Signaturen, POSITION/NORMAL/TEXCOORD_0/
WEIGHTS_0/1/JOINTS_0/1/Morph-Arrays, PSNR >= 40 dB,
8x8-Luma-SSIM >= .98 und Max-Depth-Abweichung <= .001.
Wolfram-Quervergleich: PSNR 40 dB entspricht RGB8 MSE 6.5025.
Umgeordnete Vertices sind nicht unkritisch index-identisch.
Abweichungen => NOT_COMPARABLE. Native fehlende Codec-, Morph-
oder Multi-Mesh-Faehigkeit => UNSUPPORTED ohne erfundene Frames.
ranklist_promotion = false bleibt auch fuer diese Messungen gesetzt.

Fail-closed Negativtests: truncated/header, SHA-/Laengenfehler,
JSON-Doppelschluessel/Tiefe, Count-Explosion, unbekannte
erforderliche Extension, externe Ressourcen sowie Meshopt-
Virtual-Buffer-/Payload-Bounds. Synthetische Fehlbytes sind
nur markierte negative Fixtures. Receipt: are.asset-codec-
comparison.v1, Rohzeiten, Material-/Rig-/Qualitaetsdaten,
Source-Pfad-SHAs, native Build-SHA, Bild-/Depth-Hashes
und kanonischer SHA256 des Bodies.

Nicht belegt: originale LOD1+, nativer Codec-Upgrade,
native Morph-Ausfuehrung, per-Decoder-Peak RSS,
ungepruefte Worker-2/4/8-Serien, Android/Aurion-FPS oder GPU-Paritaet.

