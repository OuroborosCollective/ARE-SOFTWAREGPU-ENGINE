## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-14 - Rasterizer and Shader Optimizations
**Learning:** Converting numpy clip and array multiplications into pure scalar/Python float alternatives improves speed significantly but requires proper `math.isnan()` checks to preserve original exception bounds (for EXACT test parity). Further casting multipliers to `np.float32` explicitly helps avoid silent float64 promotion inside array logic.
**Action:** Applied scalar unpacking and `np.float32` explicit casts for edge equations and fragment shader `np.clip` substitutions, keeping the byte-parity contracts intact while doubling fragment shader speed.
