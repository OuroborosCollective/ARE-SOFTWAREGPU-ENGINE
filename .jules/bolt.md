
## 2024-05-18 - [Optimize Blinn-Phong Fragment Shader Vector Math]
**Learning:** In hot paths like fragment shaders, replacing `np.linalg.norm` with `math.sqrt`, `np.dot` with manual scalar multiplication/addition, and `np.clip` with `min/max` bounds checking on small length-3 arrays significantly reduces overhead and speeds up performance by >2x in those functions.
**Action:** Always prefer standard Python scalar math like `math.sqrt` or `min`/`max` over `numpy` linear algebra or clipping functions when processing small, fixed-size vectors (e.g. 3D geometry coordinates or RGB colors) in highly iterated loops.
