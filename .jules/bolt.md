## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replace np.clip with scalar min/max in fragment_shader
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail due to silent NaN swallowing.
**Action:** When implementing scalar fallbacks for functions like `np.clip`, always pair them with manual exception handling (like `math.isnan(val)` checks on all color channels) to preserve NumPy's original ValueError semantics for exact-bound exact parity tests.

## 2026-10-18 - Replacing min/max math operations with inline fast-paths
**Learning:** For pure Python hot paths (like fragment shaders), inline `NaN` checks utilizing boolean comparisons (e.g., `x == x` being false for NaN) and pure Python ternary bounding (e.g., `val if 0 <= val < 1 else 1`) execute significantly faster than `math.isnan()` and built-in `min()`/`max()` functions while preserving the same logic and exception handling.
**Action:** Use inline pure python ternary checks and boolean checks for NaNs rather than `min`/`max` and `math.isnan()` builtins in critical inner loop paths where exact behaviour constraints apply and milliseconds matter.
