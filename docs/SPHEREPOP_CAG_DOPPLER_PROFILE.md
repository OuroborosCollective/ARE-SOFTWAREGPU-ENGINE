# SpherePop / Wolfram-CAG / Doppler: opt-in native CPU research profile

**Status:** Experimental; excluded from production renderer dispatch and Aurion runtime. No full GLB end-to-end benchmark, no performance claim.

## Contracts

- `native/raster/spherepop_doppler_profile.hpp` is a C++17 post-process applied **only to a separate single-object framebuffer** after the existing native rasterizer has produced real RGBA8 and float32 depth. An already composited multi-object buffer must not be recolored without a per-object ID mask/G-buffer.
- SpherePop **inspiration only**, not formal or runtime compatibility: bounded ordered Bind/Pop/Refuse/Collapse event metadata with parent indices. FNV-1a is a reproducible debug fingerprint, **not cryptographic evidence**. No SpherePop code was imported.
- Wolfram/CAG is an **offline independent numerical oracle**. No HTTP/CAG calls in the runtime and no gameplay authority.
- Classical moving-source, stationary-observer Doppler model: `f_observed/f_source = c/(c-v_radial)`; positive `v_radial` means toward observer. Distances and velocity require consistent scene units per second. The `|v_radial| < 0.95c` limit is a conservative numerical admission bound, not universal physics. This is **not** relativistic optical Doppler.
- RGB red/blue tint is an intentionally **artistic** mapping of Doppler sign. It is not an accurate light spectrum simulation or audio synthesis. Alpha and depth are untouched.
- Fail closed for nonfinite/zero sound speed, coincident observer/source, oversized velocities, bad depth/buffer size, incompatible rounding mode, FTZ/DAZ on SSE, and overfilled event history; reject before mutating output.
- No GPU backends, network, model training, third-party native code or production shader admission are changed.

## Reproduction and evidence

Wolfram Language independent input:

```wolfram
FullSimplify[{120/(120-30),120/(120+30),120/(120-0),Sqrt[(1+3/5)/(1-3/5)],(120/(120-30))*440,(120/(120+30))*440}]
(* {4/3, 4/5, 1, 2, 1760/3, 352} *)
```

The fourth entry is a **relativistic control** only; native profile does not use it.

Run:

```bash
python -m unittest software_gpu.tests.test_spherepop_doppler_profile -v
python -m unittest software_gpu.tests.test_native_raster software_gpu.tests.test_wolfram_cag_oracle -v
python -m unittest discover -s software_gpu/tests -p 'test_*.py' -v
```

The first test builds the test executable with the project's C++17 floating-point flags and calls the **actual** `are::raster::draw` before applying the optional tint. It checks stationary/approach/recede ratios, pixel/depth/alpha invariants, background isolation, deterministic event replay, failed preconditions and SSE floating-point environment restrictions.

Local source-only smoke test (20 Oct 2026): compiled with g++ and `-fno-fast-math -ffp-contract=off -Werror` and run under UBSan, PASS. This smoke uses a prepared in-memory 4x4 pixel/depth fixture; **it does not prove the real-raster integration test**. The latter must pass on the exact PR head in GitHub Actions before merge.

Local supplied asset SHA-256 audit: nine user GLBs plus one ZIP (49 entries), all match the local input manifest. High-triangle files are **not** benchmarked/rasterized by this change; no originals are committed or uploaded.

Repositories: SpherePop inspiration https://github.com/standardgalactic/spherepop and https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE . Repository license and NOTICE govern new code. No copied upstream source.
