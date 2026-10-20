## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replace np.clip with scalar min/max in fragment_shader
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail due to silent NaN swallowing.
**Action:** When implementing scalar fallbacks for functions like `np.clip`, always pair them with manual exception handling (like `math.isnan(val)` checks on all color channels) to preserve NumPy's original ValueError semantics for exact-bound exact parity tests.

## 2026-10-20 - Fast Homogeneous Buffer Clear
**Learning:** When clearing or filling homogeneous RGBA structures (like framebuffers) where all channels are simultaneously reset to a constant color, assigning per-channel slices (e.g., `buffer[..., 0] = r`) triggers slow iterator and broadcasting overhead.
**Action:** Cast the NumPy array view to `np.uint32` and use a single `fill()` operation. Pack the RGBA values on little-endian architectures as `color_val = r | (g << 8) | (b << 16) | (a << 24)`. This significantly improves clear performance (~2x faster for 1080p).
