# GLB -> native model raster -> Single-Origin time-window (experimental)

## What this proves

The focused test `software_gpu.tests.test_single_origin_glb_bridge` constructs a **real glTF 2.0 indexed GLB** with 28,800 triangles and 14,641 vertices, pins it by SHA-256, validates its binary data through the existing repository importer, and writes one typed `AREMDL01` request. The standalone C++17 entry point `native/symbolic/model_pulse_main.cpp` reads that request with the existing native `Scene` parser, recomputes the model geometry for each timestamp, and submits it to the existing CPU `rooms::Pipeline` with a native depth-buffer and final RGBA8 result.

Native diagnostic depth uses signed NDC [-1,1] while the pulse API requires a normalized [0,1] scene-depth preflight. The bridge retains original native float32 depth byte-for-byte and creates a separate, monotone normalized float32 read-only attachment before invoking the pulse. Original and projected depths are both checked unchanged after the effect; a native depth of exactly 1 is background. The earlier unconverted feed correctly failed closed with `GLB_PULSE_DEPTH_INVALID` (PR #142 initial CI Ubuntu 3.11, run 39508687502); the mapping is part of this tested integration, not a change to either existing renderer or pulse kernel.

Only **one admitted model** is accepted. The first research implementation marks depth-visible cells `owner=7`, background `owner=0`, and **rejects multi-model scenes**. That is not a general ownership system: no per-object ID buffer is supplied by the existing model rasterizer. A multi-entity production effect must use an authoritative native owner attachment, not guess ownership from depth.

At timestamps `t=0..7`, a new pristine raster is rendered, then the unchanged `single_origin::apply_at_time` kernel uses source pixel (64,64), wave speed 8, radius 48 and a 1-second half-open arrival window. It leaves float32 depth and RGBA alpha untouched. The test checks:

- True model-raster sample writes and actual projected input triangle count.
- Single origin, exactly 7,213 spatial arrivals with no duplicates; per-tick expected counts `[1,196,600,996,1416,1816,2188,0]`.
- No recoloring of background, non-target areas, or pixels outside the active time window.
- Independent replay of the same timestamp, and byte-exact output equality between native **one-worker** and **four-worker** modes for each base and wave P6 image.
- 15 alternating warmup-excluded native full-draw baseline/wave timing pairs **per worker configuration**, including native geometry recomputation, rasterization and post-effect. The raw samples and medians are emitted on the native stdout and checked by the Python regression. Different outputs are not speedup-equivalent.

This is a full `generated GLB -> native diagnostic renderer -> post-raster RGBA8 pulse` slice, **not** textured-PBR material parity, a per-object ownership buffer, a Godot comparison, the ten original owner GLBs, scene submission in live gameplay, or hardware-GPU performance. Native `sample_writes` are MSAA sample writes, not unique output pixels. The native model exporter produces 128x128 P6 frames for inspection; no external hosting is involved.

## Verification and publication gate

Run `python -m unittest software_gpu.tests.test_single_origin_glb_bridge -v`. Follow with the full repository CPU/Windows/JIT/Mesa/coverage gates on the exact PR head, and verify complete GitHub Actions results before merging. Do not claim green from file creation alone. If any gate is blocked or fails, keep the PR draft, correct the root cause, and rerun. Once genuine CI evidence is confirmed, append exactly one short line to `Memory.md` stating the change, lesson and evidence, then recheck the final head.
