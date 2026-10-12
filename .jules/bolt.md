## 2024-05-14 - Scalar Math in Hot Paths Avoids Array Wrapper Overhead
**Learning:** In the SoftwareGPU pipeline's hot paths (e.g., `fragment_shader`), replacing Numpy vector operations (`np.linalg.norm`, `np.clip`, `np.dot`) with standard Python scalar math (`math.sqrt`, `min`/`max`, and inline algebraic combinations) for small vectors (length 3 or 4) significantly improves performance by avoiding NumPy array wrapper and function call overhead during per-pixel operations. The graphics FPS increases from ~1.45 to ~2.0 under high load.
**Action:** Always consider converting small, repetitive vector math in per-pixel shaders to manual Python scalar math for performance gains, while ensuring exact mathematical compatibility.

## 2024-05-14 - Top-Level Imports in Shaders
**Learning:** Placing import statements (like `import math`) inside highly iterated hot path functions introduces massive overhead.
**Action:** Place them at the module level.
