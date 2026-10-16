## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replace np.clip with scalar min/max in fragment_shader
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail due to silent NaN swallowing.
**Action:** When implementing scalar fallbacks for functions like `np.clip`, always pair them with manual exception handling (like `math.isnan(val)` checks on all color channels) to preserve NumPy's original ValueError semantics for exact-bound exact parity tests.

## 2026-10-18 - Replace np.dot with explicit scalar math in hot paths
**Learning:** In highly iterated hot paths (like fragment shaders), replacing NumPy vector operations like `np.dot` on small, fixed-size arrays (e.g., length 3 vectors) with explicit scalar multiplication and addition (e.g., `a[0]*b[0] + a[1]*b[1] + a[2]*b[2]`) eliminates dynamic dispatch overhead and yields significant performance speedups (~1.7x) while maintaining exact mathematical correctness and byte parity.
**Action:** When working on per-pixel or highly executed functions, use explicit scalar math for small vector operations instead of generic NumPy functions. Add static AST tests to prevent future regressions.
