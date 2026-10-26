## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replace np.clip with scalar min/max in fragment_shader
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail due to silent NaN swallowing.
**Action:** When implementing scalar fallbacks for functions like `np.clip`, always pair them with manual exception handling (like `math.isnan(val)` checks on all color channels) to preserve NumPy's original ValueError semantics for exact-bound exact parity tests.

## 2026-10-18 - Rasterizer _rasterize_band Optimization
**Learning:** Precomputing edge deltas (`dx`, `dy`) and moving them out of the innermost per-pixel loop, alongside inlining barycentric calculations (replacing per-pixel `np.array` allocation), yields substantial rasterizer speedups without breaking exact byte parity.
**Action:** When manually inlining barycentric edge equation logic inside rasterizer innermost pixel loops, explicitly cast coordinates to `np.float32()` (e.g., `np.float32(px + 0.5)`) to avoid `float64` promotion, which otherwise breaks depth interpolation and exact depth buffer byte-parity contracts.

## 2026-10-18 - Rasterizer prepare_triangles Array Optimization
**Learning:** In NumPy-based hot paths (like `prepare_triangles`), replacing `np.stack` aggregation and `.all()` array reduction with explicitly unrolled boolean in-place evaluations via `.copy()` and `np.logical_and(..., out=...)` significantly eliminates multi-megabyte allocations and boosts geometric throughput. Additionally, pre-allocating an output array (e.g., `np.empty((..., 3, 3))`) is faster than `np.stack` for recombining final transformed coordinates.
**Action:** Eliminate `np.stack` and chained `.all()` when combining geometric/boundary conditionals, and instead use pre-allocated outputs (`np.empty`) or unrolled in-place boolean ops to cut allocation overhead.
