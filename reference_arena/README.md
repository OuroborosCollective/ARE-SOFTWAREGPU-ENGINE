# Three.js reference arena

A small visual reference for the supplied six GLB originals. The four character
models retain their embedded materials, textures, and animation clips; the log and
boulder are static environment objects. The camera is perspective and can be
orbited, panned, and zoomed.

This viewer is **not** the native benchmark and its FPS display is not a renderer
comparison or a game-performance claim. The reproducible CPU comparison remains
`tools/benchmark_models.py`; its current native camera/material contract is
orthographic, diagnostic-lit, and texture-free. See `docs/native-model-benchmark.md`.

## Install and run

From the repository root, using the supplied model archive:

```sh
python tools/install_reference_arena_assets.py /path/to/SoftwareGPU_Referenzarena_GLB_Modelle.zip
python -m http.server 8000 --bind 127.0.0.1 --directory reference_arena
```

Open <http://localhost:8000>. The installer verifies every selected GLB against
`evidence/original-model-manifest-v1.json`. The original model files stay local;
`reference_arena/assets/*.glb` is git-ignored and is not part of a commit or pull
request. Three.js and OrbitControls/GLTFLoader are loaded from the pinned jsDelivr
Three.js 0.180.0 modules, so an internet connection is required for the viewer.

## Arena layout

- Magier — `Charged_Spell_Cast`
- Assassinin — `Dodge_and_Counter`
- Axtkämpfer — `Axe_Spin_Attack`
- Schwertkämpfer — `Sword_Judgment`
- Statisches Umfeld — Baumstamm und Granitfelsen

Use each dropdown to select any clip embedded in that GLB. The browser FPS counter
is a view-only diagnostic; it is affected by browser, GPU, display, and resolution.
