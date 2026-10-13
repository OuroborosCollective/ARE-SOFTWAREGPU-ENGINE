
## 2024-10-13 - [Optimize BlinnPhongShader Fragment Overhead]
**Learning:** Extracting standard Python floats manually from NumPy arrays (e.g. `u, v = float(uv[0]), float(uv[1])` instead of `u, v = uv[0], uv[1]`) before passing them to Python's builtin `min`/`max` prevents internal scalar dispatch overhead from NumPy inside tight loops. It reduces per-fragment execution times without breaking exact byte parity.
**Action:** In exact-bound exact parity tested shaders, always extract array variables directly into native floats for math blocks without completely swapping NumPy functions like `np.clip` that cause parity failure.
