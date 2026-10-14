## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-14 - Replace numpy clip/dot with scalar math
**Learning:** Replaced `np.clip` and `np.dot` in the hotpath function `fragment_shader` inside `software_gpu/graphics/shader.py` to boost performance. To prevent silent promotions, explicitly cast float multiplier `diff` and `spec` into `np.float32`. Furthermore, explicit handling of NaNs logic must be included to avoid NaN swallowed exceptions and fail-closed correctness violations for byte-parity in CPU-simulations.
**Action:** When replacing Numpy clip/dot math implementations, check exact bound conditions. Check NaN to maintain original Numpy behavior explicitly so that Exact bounds error contracts inside exact-bound tests correctly throw expected ValueError exceptions.
