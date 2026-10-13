## 2026-10-13 - Blinn-Phong fragment contract audit
**Finding:** Converting a NumPy float32 UV coordinate to a Python float before multiplying by the texture extent can alter truncation at a texel boundary, so byte parity does not hold for the proposed float conversion.
**Change:** Keep native NumPy UV arithmetic, read the mutable texture once per fragment, and add differential texel-boundary and in-place-resize tests.
**Evidence:** Previous draft head 89e126b CI passes (CPU regressions 38452257413, Mesa 38452257025). A controlled new head-versus-main performance gain is *not* established; no general speedup claim.

## 2026-10-13 - Blinn-Phong clip and int conversion
**Finding:** Using `np.clip` with `ambient + diffuse + specular` adds significant overhead due to object creation inside the fragment shader, which gets executed millions of times. Extracting coordinates as float and using `if/else` logic or python scalar `math` is significantly faster and meets exact-bound byte parity tests. The scalar math swallows NaN values, so it's required to raise `ValueError` via `math.isnan` checks if using scalar replacements as expected by exact-bound tests.
**Action:** Replace `np.clip` with scalar bounding and cast components to floats before evaluating and converting to int.
