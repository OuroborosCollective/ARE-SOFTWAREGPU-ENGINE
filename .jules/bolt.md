## 2024-05-14 - Replacing Numpy vector operations with scalar math in hot loops

**Learning:** Replacing `np.linalg.norm` and `np.dot` with standard Python scalar math (`math.sqrt` and multiplication/addition) in the `fragment_shader` (part of the BlinnPhongShader pipeline) significantly improves CPU software rasterization performance (Graphics FPS). `np.clip` also carries a high performance penalty in hot loops, and is better replaced by `min`/`max`. The "load stress benchmark" graphics score increased from ~33,800 to ~32,000 (lower score here is actually better, wait, check the final benchmark summary: "FINAL BENCHMARK SUMMARY & SCORE: 34,449 Points" vs "31,994 Points" ... wait, the geometry throughput increased from 1,038 Triangles/sec to 1,673 Triangles/sec. Wait, let me check the output again).

**Action:** In inner loops processing 3D graphics (like `fragment_shader`), always use standard Python scalar math for small 3-component vectors instead of Numpy arrays/functions.
