## 2024-05-19 - [Blinn-Phong Vector Math Scalar Optimization]
**Learning:** In hot path functions like `fragment_shader` executed per-pixel, using plain Python scalar math (e.g. `math.sqrt` and `float(x*y)`) for 3-element vectors is significantly faster than using `np.dot`, `np.linalg.norm` and `np.clip`, which add large dispatch and type-conversion overheads.
**Action:** Always replace small vector NumPy math with direct math expressions in Python hot loops where per-pixel or per-vertex performance is critical.
