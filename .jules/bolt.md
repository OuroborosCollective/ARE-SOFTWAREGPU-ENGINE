## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-14 - np.clip bottleneck in per-pixel shaders
**Learning:** `np.clip` introduces significant function call overhead when operating on very small (3-element) NumPy arrays per-pixel.
**Action:** Replace `np.clip` with manual `min`/`max` scalar logic, but explicitly handle `NaN` propagation using `math.isnan` prior to cast, as exact-bound testing expects `ValueError` instead of silently casting invalid numbers to white/black values.
