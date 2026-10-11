## 2024-05-14 - Python Scalar Math is Faster than Numpy for Small Vectors
**Learning:** In hot paths (like the fragment shader called per-pixel), replacing numpy array operations (such as `np.linalg.norm` and `np.clip`) with standard Python scalar math (`math.sqrt`, `min`, `max`) for small 3-element vectors significantly improves execution speed by avoiding numpy C-API overhead.
**Action:** When optimizing loop-heavy CPU rendering code in Python, unpack small numpy arrays into scalars and use standard library math functions instead of numpy vectorized equivalents.
