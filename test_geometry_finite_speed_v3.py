import numpy as np
import time

def orig(sx, sy, ndc):
    screen = np.stack([sx, sy, ndc[..., 2]], axis=-1).astype(np.float32)
    finite = np.isfinite(screen).all(axis=(1, 2))
    return screen, finite

def opt(sx, sy, ndc, fully_inside):
    screen = np.empty(ndc.shape[:-1] + (3,), dtype=np.float32)
    screen[..., 0] = sx
    screen[..., 1] = sy
    screen[..., 2] = ndc[..., 2]
    finite = fully_inside.copy()
    for v in range(3):
        for c in range(3):
            np.logical_and(finite, np.isfinite(screen[..., v, c]), out=finite)
    return screen, finite

def run_test():
    fpos = np.random.randn(10000, 3, 4).astype(np.float64)
    fpos[..., 3] = np.abs(fpos[..., 3]) + 0.1 # w > 0
    w = fpos[..., 3]
    inv_w = 1.0 / w
    ndc = fpos[..., :3] * inv_w[..., None]
    width = 800
    height = 600
    sx = (ndc[..., 0] + 1.0) * 0.5 * width
    sy = (1.0 - ndc[..., 1]) * 0.5 * height
    fully_inside = np.ones(10000, dtype=bool)

    t0 = time.time()
    for _ in range(1000):
        screen_orig, finite_orig = orig(sx, sy, ndc)
    t1 = time.time()

    t2 = time.time()
    for _ in range(1000):
        screen_opt, finite_opt = opt(sx, sy, ndc, fully_inside)
    t3 = time.time()

    print(f"Orig: {t1-t0:.4f}s")
    print(f"Opt:  {t3-t2:.4f}s")
    print(f"Screen match: {np.allclose(screen_orig, screen_opt)}")
    print(f"Finite match: {np.array_equal(finite_orig, finite_opt)}")

run_test()
