## 2026-10-08 - [Optimizing Python Hot Paths]
**Learning:** In highly called loops inside Python (like the fragment shader), numpy array operations like `np.linalg.norm`, `np.dot`, and `np.clip` carry a significant function call and type-checking overhead that vastly outweighs the SIMD benefits on tiny arrays (e.g. 3-element vectors).
**Action:** Unroll short vector operations into scalar math using standard Python primitives and the `math` module (like `math.sqrt`) when executing inside a tight Python loop instead of using numpy arrays. Pre-calculate loop invariants in `__init__`.
