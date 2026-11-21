# Visual Asset Lab Phase 2: native AREMDL03 PBR/Depth and three-view diagnostics

**Scope:** opt-in, local-only, read-only native asset QA. The C++17 AREMDL03
`native/symbolic/model_main.cpp` worker is the sole beauty/depth renderer;
this tool does not implement another shaded rasterizer.

## Run

Requires NumPy, Pillow (`software_gpu[model-pbr]`), a C++17 compiler and a
local, SHA-pinned glTF 2.0 GLB with embedded BIN, opaque material and supported
normals/UV. For example a private manifest:

```json
{
  "camera": {
    "eye": [1.33, 2.33, 6], "target": [1.33, 2.33, 3],
    "up": [0, 1, 0], "fov_y_degrees": 55, "near": 0.1, "far": 12
  },
  "assets": [
    {
      "id": "owner-lod0",
      "path": "/private/assets/owner-lod0.glb",
      "sha256": "<exact-lowercase-64-character-SHA256-from-private-receipt>",
      "bytes": 12345
    }
  ]
}
```

The literal placeholder above **must be replaced** with the real SHA-256 and
byte size; otherwise admission fails closed. Do not commit private manifests.

```bash
python -m tools.visual_asset_lab_native /private/manifest.json \
  --output-dir /private/empty-output-not-yet-existing --pixels 64
python -m unittest software_gpu.tests.test_visual_asset_lab_native -v
```

Output per asset: `beauty.png`, `beauty.bmp`, `native-rgba8.bin`,
`native-depth.f32le`, `wireframe.svg`, `uv_seams.svg` and a top-level
`receipt.json`. The PNG and BMP digest covers encoded file bytes; the
`native-rgba8.bin` digest covers uncompressed renderer framebuffer bytes;
the float32 little-endian depth digest is separate. Depth is **not** an
8-bit visualization. Source SHA, material canonical-JSON SHA, original embedded
image bytes SHA, AREMDL03 request SHA, native build/source SHA, fixed camera,
worker-pair parity, known missing shadow functionality and material/normal
statuses are in the receipt.

## Truth boundaries

- Beauty = actual C++17 worker resolved RGBA8 (1 vs 2 workers checked),
  depth = same worker's Float32 output. Not synthetic images.
- Wireframe and UV-seam SVG = source-derived, projected geometric diagnostics;
  they do **not** use the native raster depth buffer, do **not** show occlusion
  and are **not** a second shading authority. A boundary edge is not an
  automatically inferred UV seam.
- Renderer still applies fixed yaw/pitch and automatic per-model normalization;
  different LOD geometry may receive different effective fits. The receipt
  states `same_camera_different_native_fit_not_visually_equivalent` rather
  than claiming camera-equivalent visual quality. Reframe externally only
  with a separate verified native shared-fit contract.
- Native shadows and external texture URI resolution are not implemented;
  no fake shadow status, quality verdict or material equivalence is produced.
- Only supported **static** one-primitive indexed opaque GLB 2.0 assets,
  up to 50k source triangles for SVG overlay and at most 8 assets. Unsupported
  2M+ triangle originals and multi-primitive glTFs fail closed; do not
  silently truncate, replace or decimate original models.
- No network/UI API; local CLI only. Rejects source symlinks, file/HTTP URIs,
  wrong size/hash, external image URIs, repeated asset IDs, unsupported
  accessors, unsafe output overwrites; output is staged and published only
  after native comparisons succeed. Do not commit private GLBs or manifests.
- No native 15-paired end-to-end A/B performance benchmark here, no FPS
  inference and no leaderboard promotion. Issue #103 still requires native
  30k/12k/4k owner assets and verified timing/visual acceptance.

## Production classifications

- **Production:** unchanged; opt-in CLI only.
- **Tests:** real generated embedded GLB fixture; native 1/2 worker parity,
  negative hash/URI/fits, image/raw/depth payloads, catalog snapshot.
- **Persistence:** local SHA-bound artifacts/receipt, no gameplay state.
- **Effects:** PNG/BMP actual native beauty, SVG geometry/UV seam diagnostics.
- **Core:** existing C++17 native renderer untouched; no Aurion authority path.
- **Runtime projection:** no HTTP/Android/Gradio/Unity runtime claim.

The separate pilot `tools.visual_asset_lab` stays unchanged and remains
geometry-only. The #282 implementation does not replace it.
