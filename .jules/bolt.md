## 2026-10-12 - Scalar Math in Shader Hot Paths
**Learning:** Using np.linalg.norm and np.clip inside python inner loops (like fragment shaders) causes massive overhead for small 3D vectors.
**Action:** Replace numpy vector length and clip operations with python math.sqrt and min/max for hot shader execution paths.
