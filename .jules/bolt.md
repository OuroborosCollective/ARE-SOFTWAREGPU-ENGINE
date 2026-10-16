## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replace np.clip with scalar min/max in fragment_shader
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail due to silent NaN swallowing.
**Action:** When implementing scalar fallbacks for functions like `np.clip`, always pair them with manual exception handling (like `math.isnan(val)` checks on all color channels) to preserve NumPy's original ValueError semantics for exact-bound exact parity tests.

## 2026-10-16 - Replace np.dot with explicit scalar multiplication in fragment shader
**Learning:** `np.dot` incurs significant overhead when called on small length-3 vectors within the highly iterated `fragment_shader` (one call per fragment/pixel). By replacing `np.dot(a, b)` with explicit scalar multiplication and addition `a[0]*b[0] + a[1]*b[1] + a[2]*b[2]`, we eliminate numpy's array dispatch and function call overhead, increasing the performance without sacrificing readability much.
**Action:** Always prefer explicit scalar operations for small fixed-size vector math in highly iterated hot paths rather than relying on high-level NumPy functions that involve type checking and dynamic dispatch.
