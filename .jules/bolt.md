## 2024-05-24 - [Avoid Numpy overhead for small vectors in shaders]
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., shaders), replacing Numpy vector operations with standard Python scalar math (such as `math.sqrt` or `min`/`max` instead of `np.linalg.norm` or `np.clip`) for small vectors is a proven pattern for significantly improving performance.
**Action:** Use scalar Python operations instead of Numpy arrays and functions within tight loops like the `fragment_shader` function.
