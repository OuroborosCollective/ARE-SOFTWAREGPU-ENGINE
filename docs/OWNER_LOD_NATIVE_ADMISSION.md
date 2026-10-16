# Owner high-poly native PBR LOD admission

Issue: https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/issues/103

Two distinct uploaded owner models: Forest Lord (2,292,680 triangles; GLB and equivalent FBX) and Emerald Grass Patch (1,414,062 triangles; ZIP-packaged FBX).

Six prior LOD exports at 30k/12k/4k triangles have no NORMAL accessor. AREMDL03 PBR requires glTF normals; the offline, source-SHA-bound `tools/owner_lod_native_normals.py` adds area-weighted vertex normals while preserving the original geometry, UV, image and material data. No original files are overwritten. Does not produce a rig or animation.

Reproduction:

```bash
python tools/owner_lod_native_normals.py --input /private/forest-lord_lod0_30k.glb --output /private/native/forest-lord_lod0_30k.glb --expected-sha256 cd70bfccb4bf67e5140f61dbee2f20e1180357a06b570435da6bd455daf5e378
```

The output file hashes for the repaired six LODs and grass original are pinned in `evidence/owner-lod-native-manifest-20261016.json`. This is metadata only; private source assets are not uploaded to GitHub.

The native bridge test uses a tiny real embedded-texture GLB fixture and requires real C++17 AREMDL03 color/depth worker parity. It is not a benchmark of the owner's 2M-triangle mesh.

A clean checkout and SHA-exact private local asset copies are required for full real original-vs-LOD native benchmark:

```bash
python tools/benchmark_owner_lods.py --manifest evidence/owner-lod-native-manifest-20261016.json --assets /private/all-eight-glbs --output /tmp/are-owner-lod-native --seconds 1800 --repeats 15 --pixels 128
```

The opt-in benchmark records compiler/build identity, source hashes, 15 actual CPU runs, median, IQR, MAD, raw timing, full color/depth parity between worker counts, and render receipts. Sequential measurements are descriptive rather than paired trials. Fail closed on absent assets, wrong hash, wrong triangle counts or incomplete native frames.

Observed earlier Mesa/VTK CPU external preview at 640px: Forest Lord 11.08x and Grass 8.20x from original to LOD 30k. These are not native ARE performance numbers, Android FPS, or Godot device test results. Device-side grass instancing, RAM/overdraw and distance thresholds are still pending.
