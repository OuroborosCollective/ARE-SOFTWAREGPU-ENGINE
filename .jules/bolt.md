## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replace np.clip with scalar min/max in fragment_shader
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail due to silent NaN swallowing.
**Action:** When implementing scalar fallbacks for functions like `np.clip`, always pair them with manual exception handling (like `math.isnan(val)` checks on all color channels) to preserve NumPy's original ValueError semantics for exact-bound exact parity tests.

## 2026-10-22 - Rasterize Band Array Allocations
**Learning:** In the innermost pixel loops of the `bands` rasterizer backend, array allocations (`p = np.array([p_x, p_y])`) and generic function calls for evaluating barycentric edge equations significantly bottleneck pure geometry evaluation. Replacing these with explicitly unrolled scalar edge logic pre-calculating deltas and inline coverage checks yields a 3x speedup.
**Action:** When optimizing tight nested pixel loops, always hoist static variables (like edge deltas) out of the loops, and inline equation checks. However, strictly apply required float casts (e.g. `np.float32(p_y + 0.5)`) exactly as the baseline does to avoid silent Python `float64` promotion, maintaining byte parity with exact tests.
