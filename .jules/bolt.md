## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replace np.clip with scalar min/max in fragment_shader
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail due to silent NaN swallowing.
**Action:** When implementing scalar fallbacks for functions like `np.clip`, always pair them with manual exception handling (like `math.isnan(val)` checks on all color channels) to preserve NumPy's original ValueError semantics for exact-bound exact parity tests.

## 2026-10-18 - Rasterizer _rasterize_band Optimization
**Learning:** Precomputing edge deltas (`dx`, `dy`) and moving them out of the innermost per-pixel loop, alongside inlining barycentric calculations (replacing per-pixel `np.array` allocation), yields substantial rasterizer speedups without breaking exact byte parity.
**Action:** When manually inlining barycentric edge equation logic inside rasterizer innermost pixel loops, explicitly cast coordinates to `np.float32()` (e.g., `np.float32(px + 0.5)`) to avoid `float64` promotion, which otherwise breaks depth interpolation and exact depth buffer byte-parity contracts.

## 2026-10-25 - Rasterizer loop-invariant barycentric exact byte-parity
**Learning:** When optimizing float32 calculations (like barycentric equations) via loop-invariant code motion, strictly extract intact sub-expressions rather than expanding or rearranging algebraic terms (e.g., do not expand `(p_x - s1x) * dy` to `p_x * dy - s1x * dy`). Changing the evaluation tree alters floating-point truncation and breaks exact byte-parity tests.
**Action:** Always extract the exact y-dependent component (e.g. `w0_y_term = (p_y - s1y) * dx12`) and substitute it directly into the unexpanded original expression (e.g., `w0 = (p_x - s1x) * dy12 - w0_y_term`) to preserve precision.

## 2026-10-26 - Geometry vector bounds consolidation (#176 into #177)
**Learning:** Preserve the exact signed homogeneous plane predicates and fixed three-vertex order while removing a temporary `(F,3,7)` stack; real raster parity is the authority, not isolated Python-array speed claims.
**Action:** Use in-place `np.logical_and` per plane/vertex, preserve float64 clip-distance input and existing float32 screen projection; require exact geometry-oracle and renderer CI on the combined branch before integration.

## 2026-10-30 - Optimize array allocation and reduction in geometry setup
**Learning:** `np.stack` and `.all()` introduce measurable function dispatch, array allocation, and reduction loop overheads on small, fixed-size arrays during geometry processing.
**Action:** Replace `np.stack` with a pre-allocated `np.empty` array mapped element-wise, and replace `.all()` on fixed axes with unrolled bitwise logical AND (`&`) operations on the constituent elements. Preserve ellipsis (`...`) indexing to support arbitrary broadcasting if present in the original design.

## 2026-10-31 - HTTP Server Network Error Tolerance
**Learning:** Calling `self.http()` in Python tests using standard `http.client` may occasionally encounter `ConnectionAbortedError` or `ConnectionResetError` (especially under Windows/heavy loads) on forced TCP termination limits, which shouldn't falsely fail exact bounds tests.
**Action:** Surround expected rejection boundary HTTP request calls with try/except blocks to explicitly swallow `ConnectionAbortedError` and `ConnectionResetError` and verify the expected HTTP response code and error message.
