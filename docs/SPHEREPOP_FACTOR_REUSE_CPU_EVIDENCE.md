# Opt-in SpherePop Doppler factor reuse (C++17)

This is an intentionally **narrow** optimization of the merged CAG-seeded SpherePop experiment: the old wavefront computes a Doppler factor for an area and recomputes that factor inside `apply_single_object` for visible, non-seed pixels. The new optional `reuse_factor=true` uses the first validated factor to apply the identical artistic tint, without changing propagation geometry, receipt fingerprint, area ordering, depth, ownership or alpha. The default remains `false` to preserve existing callers. This is not a full SpherePop formal semantics implementation and does not activate a production renderer.

The native C++17 `spherepop_factor_reuse_test.cpp` draws two real triangles on the existing native raster core at 32x32 and 64x64. It checks old and new modes for **byte-identical RGBA8, float32 depth and each event's owner, emitter, arrival time, Doppler factor, tint and event fingerprint**; no mocks. It repeats across 4 velocities, two CAG seeds, and with Doppler disabled. All areas must complete exactly once and repeated wavefront arrivals must still be refused. Invalid depth must reject without modifying RGBA. Native `WaveReceipt.doppler_factor_evaluations` counts actual calls: with Doppler on, old = (areas−1) + visible non-seed cells; new = areas−1, without Doppler both 0. This is an instrumentation receipt, not an independent CPU profiler.

15 alternating CPU runs per 32/64-pixel fixture include the actual native draw and full effect. Each run checks the exact final result and emits raw times to the CI log. **Only a completed SHA-bound CI run may produce performance claims**: faster/slower changes with CPU, scheduler, matrix and workload. A median speedup >1 must not be assumed.

```bash
python -m unittest software_gpu.tests.test_spherepop_factor_reuse -v
python -m unittest discover -s software_gpu/tests -p 'test_*.py' -v
```

The earlier four-way ranking in [PR #134](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/pull/134) remains the correct baseline. This benchmark cannot be mixed with the Python-tiles ranker nor interpreted as real GLB/production FPS. If measured, report the optimized-vs-legacy ratio separately with the full native-core context. Do not modify the main README until the opt-in fast path passes exact-head CI and yields a source-bound timing result.
