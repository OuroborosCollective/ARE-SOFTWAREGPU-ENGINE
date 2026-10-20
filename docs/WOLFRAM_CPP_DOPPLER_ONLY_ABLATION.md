# Wolfram + C++17 Doppler-only CPU research ablation

**Separated implementations.** `native/raster/doppler_only.hpp` contains no SpherePop includes, history, priority queue, area-propagation or event callbacks. A source position and classical source velocity directly determine an independent pixel's Doppler factor. A distinct object-owner mask prevents changes to unrelated objects, and the result preserves the canonical RGBA alpha and all float32 depth bits. Failed admission leaves all RGBA unchanged. Source pixels have the neutral factor 1 (no line-of-sight direction).

**Independent Wolfram reference:**
```wolfram
FullSimplify[{120/(120-30),120/(120+30),120/(120-0),
              120/(120-30/Sqrt[2]),120/(120+30/Sqrt[2]),
              Sqrt[(1+3/5)/(1-3/5)]}]
(* {4/3, 4/5, 1, 4(8+Sqrt[2])/31, 4(8-Sqrt[2])/31, 2} *)
```
The last `2` is a relativistic control, not used by this classical profile. RGB red/blue tint remains an artistic mapping, **not physical spectral radiance**. There is no on-render Wolfram HTTP call and no GPU implementation.

The native test renders **real C++17 triangles** with `are::raster::draw`, then measures 32×32 and 64×64 raster frames in **three conditions**: baseline native render, direct Doppler-only, and CAG-seeded SpherePop+Doppler. It alternates conditions for 15 CPU samples after warmups, compares deterministic full-buffer replays and unchanged depth/alpha, and emits the measured native raw milliseconds, per-scene medians and paired ratios to the CI logs. `Doppler-only` and `SpherePop+Doppler` intentionally produce *different* RGB data: the former references the original source, the latter propagates through previous local emitters. Matching them pixel-by-pixel is neither expected nor a valid test.

**Numerical contract:** classical stationary-observer/moving-source Doppler, speed and positions in internally consistent units. Rejects nonfinite input, velocity budget violations, non-nearest rounding, SSE FTZ/DAZ, inconsistent buffers or invalid depth. Source/observer coincidence is neutral. Float64 geometric factor does not claim byte-equivalent physical accuracy of arbitrary float32 pipelines.

```bash
python -m unittest software_gpu.tests.test_doppler_only -v
python -m unittest discover -s software_gpu/tests -v
```

This is a bounded research experiment, not production activation. CPU-only same-runner A/B ratios are not hardware-GPU FPS and cannot be compared directly to prior distinct scenes/hosts.
