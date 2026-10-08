"""Optional LLVM-compiled CPU tile coverage kernel (Numba, never GPU).

The kernel computes triangle coverage, barycentric weights and early depth
decisions. Programmable Python fragment shaders remain intentionally outside
the JIT boundary. The compiled path is opt-in, with explicit dependency errors.
"""
from functools import lru_cache

import numpy as np


def _coverage_kernel(s0, s1, s2, left, right, top, bottom, inv_area, depthbuf):
    height = bottom - top + 1
    width = right - left + 1
    capacity = height * width
    rows = np.empty(capacity, dtype=np.int32)
    cols = np.empty(capacity, dtype=np.int32)
    alphas = np.empty(capacity, dtype=np.float32)
    betas = np.empty(capacity, dtype=np.float32)
    gammas = np.empty(capacity, dtype=np.float32)
    depths = np.empty(capacity, dtype=np.float32)
    n = 0
    for y in range(height):
        py = np.float32(top + y) + np.float32(0.5)
        for x in range(width):
            px = np.float32(left + x) + np.float32(0.5)
            w0 = (px-s1[0])*(s2[1]-s1[1]) - (py-s1[1])*(s2[0]-s1[0])
            w1 = (px-s2[0])*(s0[1]-s2[1]) - (py-s2[1])*(s0[0]-s2[0])
            w2 = (px-s0[0])*(s1[1]-s0[1]) - (py-s0[1])*(s1[0]-s0[0])
            if w0 >= 0 and w1 >= 0 and w2 >= 0:
                a = w0 * inv_area
                b = w1 * inv_area
                c = w2 * inv_area
                z = a * s0[2] + b * s1[2] + c * s2[2]
                if z < depthbuf[y, x]:
                    rows[n] = y
                    cols[n] = x
                    alphas[n] = a
                    betas[n] = b
                    gammas[n] = c
                    depths[n] = z
                    n += 1
    return (rows[:n], cols[:n], alphas[:n], betas[:n], gammas[:n], depths[:n])


@lru_cache(maxsize=1)
def get_compiled_coverage():
    """Return a native LLVM CPU kernel; no automatic fallback or mock execution."""
    try:
        from numba import njit
    except ImportError as exc:
        raise RuntimeError(
            "tiles-jit requires optional Numba; install software_gpu[jit]"
        ) from exc
    return njit(cache=True, nogil=True, fastmath=False)(_coverage_kernel)
