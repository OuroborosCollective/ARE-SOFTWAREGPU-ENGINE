# SpherePop-CAG-Doppler CPU ranking: real paired benchmark

The repo already contains an isolated native C++17 CAG/SpherePop radial Doppler wave (PR #127). This new research-only benchmark wraps that **unmodified native wave** with a bounded C ABI, loads it into the actual `SoftwareRasterizer` CPU process, and times whole `draw_mesh` with and without the wave.

**Controlled workloads:** seed 1234 / 8 large triangles; seed 991 / procedural 400 triangles; square 32 and 64 pixels (the wave's source contract currently rejects dimensions above 64). Existing archive measurements at 128/256 pixels are **not comparable** to this run and must not be used to claim a new speedup.

Three real CPU raster backends: `tiles`, `batch-first`, and `native-cpp`. For each scene and resolution, every backend receives 15 alternating on/off paired runs after warmup. Timing includes Python geometry preparation + real raster draw, then (enabled only) generation of the uint32 object-owner mask from depth and calling the native radial wave. Framebuffer clear and hashing are outside timing, equally in all modes. Build/compile is outside timing. Total attempts: 4 scenes/resolutions x 3 backends x 2 conditions x 15 repeats = **360 measured full-draw executions** plus warmups.

**Results:** individual timings, median/IQR/MAD, paired ratios `tiles+wave / backend+wave` and `backend without wave / backend with wave`; required RGBA8+float32-depth byte equality between backends separately for wave-off and wave-on, wave effect must change RGB but never depth, repeatable event fingerprint. No fake times. The exact head SHA, native compiler/source/binary digests, environment and full positive samples are recorded in JSON.

**CI:** `python -m unittest software_gpu.tests.test_spherepop_wave_ranked_benchmark -v` runs on Linux as part of canonical CPU regression tests; Windows still executes existing native wave regressions. CI log prints the digest-bound run's concise results. Until that CI produces a numeric report, **no new 1.88x or other speedup exists**. Existing 128/256 px leaderboard values are historical evidence, not proof for the new effect.

The source **does not** claim to accelerate general rasterization, to render a full textured GLB, or to compare against hardware GPU. Wave-on versus wave-off changes RGB by design; parity means same output for different backends at the same wave setting, not comparing wave-on RGB to wave-off RGB.

Manual reproduction:
```bash
python -m software_gpu.benchmarks.compare_spherepop_wave_frames --output wave-ranked.json --pixels 32 64 --repeats 15 --max-seconds 600
```
