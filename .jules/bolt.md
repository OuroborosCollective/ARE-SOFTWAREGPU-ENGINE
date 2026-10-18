## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replace np.clip with scalar min/max in fragment_shader
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail due to silent NaN swallowing.
**Action:** When implementing scalar fallbacks for functions like `np.clip`, always pair them with manual exception handling (like `math.isnan(val)` checks on all color channels) to preserve NumPy's original ValueError semantics for exact-bound exact parity tests.

## 2026-10-18 - Avoid incremental barycentric addition for byte-parity
**Learning:** In innermost rasterization loops, incrementally calculating barycentric coordinates (e.g. `w0 += e0_y` per pixel) instead of evaluating them explicitly causes floating-point accumulation drift, resulting in byte-parity failures in exact-bound integration tests.
**Action:** When inlining edge evaluations to eliminate function calls and array allocations, precompute the shared components (e.g. `w0_y_part`) but calculate the final value via explicit evaluation per pixel (e.g. `w0 = (p_x - s1_x) * e0_y - w0_y_part`) rather than DDA-style increments to preserve NumPy exact equivalence.
