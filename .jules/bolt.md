## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replacing np.clip with pure scalar math in fragment shader
**Learning:** `np.clip` incurs significant overhead when called on small arrays within the fragment shader's hot path (e.g., inside per-pixel loops). Replacing it with pure scalar math (using simple `if/else` or `min/max`) yields substantial performance improvements but requires explicit `NaN` handling because exact-bound tests expect `NaN` inputs to raise exceptions, which scalar operations silently swallow.
**Action:** Replace `np.clip` with scalar operations inside highly iterated fragment shaders for performance. Ensure `math.isnan()` checks are included to explicitly raise a `ValueError` to preserve correct error semantics and byte-parity in the testing suite.
