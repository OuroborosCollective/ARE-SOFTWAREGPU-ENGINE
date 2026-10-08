# Aurion second original GLB batch — complete LOD1/LOD2 pairs

The owner confirmed that **arena_courtyard** and **fountain** have **exactly two created LOD levels: LOD1 and LOD2**. LOD0, LOD3 and LOD4 were not provided or created for these pairs and are **NOT requirements or missing-data defects**. The separate street lamp has its own LOD0–LOD3 four-step chain.

All four original owner-uploaded GLB2 files were read and SHA-256-verified locally. Real mesh contents: 1 mesh / 1 indexed triangle primitive / 1 material / 3 embedded 2048×2048 JPEG images per file. Exact source hashes and 3D metadata are in the two separate machine-readable manifests.

| Asset | LOD1 triangles | LOD2 triangles | Reduction | LOD1 GLB bytes | LOD2 GLB bytes | Reference mask IoU |
|---|---:|---:|---:|---:|---:|---:|
| Arena courtyard | 2781 | 1818 | 34.63% | 7575264 | 7520104 | 0.98763 |
| Fountain | 2132 | 1053 | 50.61% | 7316404 | 7274952 | 0.95846 |

**Provenance:** Source `arena_courtyard_LOD1(1).glb`, `arena_courtyard_LOD2(1).glb`, `fountain_LOD1.glb`, `fountain_LOD2.glb`, attached by the owner in ChatGPT, 2026-10-09. SHA-256 pins are mandatory; never silently replace a missing file.

**Independent local reference observation (not ARE):** A CPU-only geometry renderer loaded all four original GLB files and generated two identical screen/depth-mask outputs per model using a fixed orthographic camera and 224×224 pixels. The resulting pairwise silhouette intersection-over-union was 0.98763 for arena and 0.95846 for fountain. Images are independent geometry-only diagnostics; **not** Aurion WebGL/WebGPU or texture/PBR screenshots. The measurements were made on a local machine, not a GitHub Actions worker.

**ARE integration:** The existing `software_gpu.integrations.aurion.offline_lod_worker` now accepts the *exact* names in either batch manifest while preserving the four-step street-lamp manifest. No third/fourth level is synthesized. The replay runner remains read-only, hash-gated, killable and CPU-only.

```bash
python -m software_gpu.integrations.aurion.offline_lod_worker --manifest fixtures/aurion/arena_courtyard/manifest.json --model-dir /path/to/originals --output-dir /tmp/aurion-arena --pixels 192 --repeats 2
python -m software_gpu.integrations.aurion.offline_lod_worker --manifest fixtures/aurion/fountain/manifest.json --model-dir /path/to/originals --output-dir /tmp/aurion-fountain --pixels 192 --repeats 2
```

The actual original GLB binaries are **not** checked into GitHub. GitHub CI validates manifests and parser/renderer behavior using generated GLB geometry. No full-original ARE rendering in GitHub CI is claimed. This work is a bounded fixture-extension subtask of **Issue #6**, not proof of runtime FPS benefit or a change in Aurion's world/gameplay authority.

**Important performance insight:** The original LOD pairs share unchanged 2048×2048 textures; reducing triangles has almost no effect on transferred GLB bytes, so texture / MIP / compression optimization is a separate research path.
