## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replace np.clip with scalar min/max in fragment_shader
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail due to silent NaN swallowing.
**Action:** When implementing scalar fallbacks for functions like `np.clip`, always pair them with manual exception handling (like `math.isnan(val)` checks on all color channels) to preserve NumPy's original ValueError semantics for exact-bound exact parity tests.

## 2026-10-18 - Inline edge functions in rasterizer pixel loop
**Learning:** Removing `np.array` allocation and explicitly unrolling edge equation functions inside pixel innermost loops yields huge performance improvements, but causes exact depth buffer byte-parity tests to fail if float64 is accidentally introduced. Using pure Python floats for position coordinates causes evaluation in float64, altering depth interpolation.
**Action:** When manually inlining barycentric edge equation logic inside rasterizer innermost loops, ensure `p_x` and `p_y` are explicitly cast using `np.float32(val)` so that all downstream arithmetic remains native numpy `float32`, preserving exact byte parity.
