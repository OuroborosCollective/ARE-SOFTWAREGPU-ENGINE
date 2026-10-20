# Native wave sequence and indexed GLB stress (research)

This slice extends the isolated **single-origin** C++17 research validation; it does not change the production renderer, game state, or the wave kernel.

## Native eight-frame sequence

Run `python -m unittest software_gpu.tests.test_single_origin_time_window -v`. The native test renders two real triangles from pristine color/depth buffers for timestamps t=0 through t=7. Every timestamp uses the existing `apply_at_time` function, not a persistent queue. The frame pass checks RGBA replay, object ownership, alpha, float32 depth, zero reemissions/queue pushes, and exactly-once coverage of a radius-48 disc centered at (64,64) on 128x128. Independent integer-circle membership oracle via Wolfram: frame area counts `[1,196,600,996,1416,1816,2188,0]`; exactly 7,213 areas total.

An optional direct native invocation `./time_wave --frames-dir /existing/output/directory` writes eight binary P6 PPM files. The Python regression runs the executable twice, validates PPM headers and payload sizes, and compares SHA-256 of every frame. This is an **offline frame sequence**, not production video/animation, and not a claim of FPS improvement.

## Generated GLB stress

Run `python -m unittest software_gpu.tests.test_single_origin_glb_stress -v`. A generated valid indexed GLB contains **28,800 nondegenerate triangles** and **14,641 unique grid vertices** with a sinusoidal height profile. It is decoded via the project's existing SHA-pinned glTF parser, submitted as an actual typed native AREMDL request, then rasterized with 1 and 4 native CPU workers for two repeated frames. Full color/depth parity, output hashes, nonzero raster work, and source integrity are required.

**Boundary:** this is a separate native model-render path. The experiment does **not yet apply the time-window pulse to GLB ownership and depth buffers**; such a bridge must be scoped and tested independently. Owner original GLB binaries are not present in the repository and are not committed. The generated GLB is not a surrogate for those original assets.

## Integration requirements

Run focused native tests, full Linux/Windows CPU regressions, LLVM-JIT, wheel/CLI and UI checks on the exact PR head. Preserve coverage floors. If checks fail, fix and rerun before merge. Only after verified evidence append one short change + lesson + evidence entry to `Memory.md`, then verify the final head again. Treat green tests as proof of their test contracts only, not production or Android FPS.
