## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-16 - Replace np.clip with scalar min/max in fragment_shader
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing NumPy functions like `np.clip` with pure scalar equivalents (e.g., `min`/`max` on floats) improves performance by reducing overhead, but can cause exact byte-parity tests to fail due to silent NaN swallowing.
**Action:** When implementing scalar fallbacks for functions like `np.clip`, always pair them with manual exception handling (like `math.isnan(val)` checks on all color channels) to preserve NumPy's original ValueError semantics for exact-bound exact parity tests.
## 2026-10-16 - Replaced np.dot and np.linalg.norm with scalar math
**Learning:** In highly iterated hot paths (like fragment shaders), replacing NumPy vector operations like `np.dot` and `np.linalg.norm` on small, fixed-size arrays (e.g., length 3 vectors) with explicit scalar multiplication and addition eliminates dynamic dispatch overhead and yields significant performance speedups while maintaining exact mathematical correctness and byte parity.
**Action:** Use scalar math instead of NumPy vector operations for small, fixed-size arrays in hot paths to avoid dispatch overhead.
## 2026-10-16 - json.loads parameters
**Learning:** In Python 3.11, the  function does not accept the  parameter, but it does accept the  parameter to handle , , and .
**Action:** Use  instead of  to reject  values in .
## 2026-10-16 - json.loads parameters
**Learning:** In Python 3.11, the json.loads function does not accept the allow_nan=False parameter, but it does accept the parse_constant parameter to handle NaN, Infinity, and -Infinity.
**Action:** Use parse_constant=lambda _: (_ for _ in ()).throw(ValueError()) instead of allow_nan=False to reject NaN values in json.loads.
