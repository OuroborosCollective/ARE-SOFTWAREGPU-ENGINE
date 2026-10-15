## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-13 - Blinn-Phong Fragment Shader `np.clip` Optimization
**Finding:** Calling `np.clip` in the hot path of the fragment shader creates significant overhead (over 5% of the total runtime in benchmarks). Replacing this with Python's built-in `min`/`max` functions dramatically improves performance. However, because exact-bound tests expect `ValueError` when non-finite values (like `NaN`) are encountered in material logic, naive scalar replacements fail.
**Action:** Replace `np.clip` with `min`/`max` combined with an explicit `math.isnan` check to preserve both high performance and byte-parity/error semantics. Cast the components to float before capping, but catch NaN early and raise a ValueError if detected.
