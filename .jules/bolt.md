## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.
## 2026-10-15 - Blinn-Phong fragment optimization with scalar operations
**Learning:** `np.clip` incurs large overhead in hot paths like the `fragment_shader` (measured at ~0.9s vs ~0.2s for scalar logic for 100k ops). But replacing it requires extreme care with implicit `NaN` propagation across all channels (r,g,b), otherwise exception contracts from exact-bound tests will silently fail.
**Action:** When migrating from `np.clip` to scalar truncation, ensure comprehensive `math.isnan()` checks are added *for all scalar channels* if the original NumPy exception behavior is mandated by the test gate.
