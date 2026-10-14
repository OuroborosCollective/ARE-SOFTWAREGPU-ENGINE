## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.
## 2026-10-15 - Blinn-Phong Fragment np.clip scalar replacement
**Learning:** Pure Python scalars with min/max combined with manual math.isnan checks bypass `np.clip` overhead entirely without failing exact byte-parity. The exception contract that `np.nan` evaluates strictly to exceptions in `np.clip` must be explicitly recreated.
**Action:** Replace `np.clip` in per-pixel hot paths with scalar logic and explicitly test for NaNs if the exact test suite expects a ValueError.
