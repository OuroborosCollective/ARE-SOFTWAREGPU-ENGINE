## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-14 - Replace np.clip with pure scalar equivalents
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail. This replacement must be paired with manual exception handling (e.g. `math.isnan`) to preserve NumPy's original error semantics.
**Action:** Use scalar `min`/`max` and check for `NaN` when replacing `np.clip` to maintain test parity while gaining performance.

## 2026-10-14 - Use Python scalar min/max over np.clip in hot paths
**Learning:** Replacing NumPy `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance in exact-bound hot paths. However, exact byte-parity tests might fail if `NaN` swallowing behavior changes.
**Action:** The replacement must be paired with manual exception handling to preserve NumPy's original error semantics (using `math.isnan`).
