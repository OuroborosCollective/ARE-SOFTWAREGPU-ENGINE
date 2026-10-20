## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replace np.clip with scalar min/max in fragment_shader
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail due to silent NaN swallowing.
**Action:** When implementing scalar fallbacks for functions like `np.clip`, always pair them with manual exception handling (like `math.isnan(val)` checks on all color channels) to preserve NumPy's original ValueError semantics for exact-bound exact parity tests.
## 2026-10-20 - Fast Array Fill on RGBA Buffers
**Learning:** In highly iterated buffer clears (like `Framebuffer.clear`), assigning 8-bit slices per channel (`self.color_buffer[..., 0] = r`) incurs heavy NumPy iteration overhead. Casting the multi-channel array view to `np.uint32` and utilizing a single `fill()` operation bypasses this, yielding a nearly 9x performance improvement for array-wide constants.
**Action:** When clearing or filling homogeneous RGBA structures where all channels are simultaneously reset to a constant color, pack the target into a single 32-bit integer (e.g., `r | (g << 8) | (b << 16) | (a << 24)` on little-endian architectures) and use a `.view(np.uint32).fill()` operation instead of separate slice assignments.
