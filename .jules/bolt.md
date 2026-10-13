## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-14 - Overhead of np.clip in hot paths
**Learning:** Using `np.clip` in highly iterated hot paths like the `fragment_shader` introduces significant per-pixel overhead. Decomposing it into standard Python scalar math (`max`, `min` on floats) is noticeably faster and raises the geometry throughput, especially in extreme test stages. However, because `max`/`min` swallow `NaN` values, explicit `math.isnan` checks are required to maintain strict exception contracts.
**Action:** Replace `np.clip` with `math.isnan` guards and scalar `max`/`min` in per-pixel rendering loops to eliminate array object overhead.
