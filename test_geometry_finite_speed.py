import numpy as np
import time

def orig(screen):
    return np.isfinite(screen).all(axis=(1, 2))

def opt(screen, fully_inside):
    finite_opt = fully_inside.copy()
    for v in range(3):
        for c in range(3):
            np.logical_and(finite_opt, np.isfinite(screen[..., v, c]), out=finite_opt)
    return finite_opt

def run_test():
    screen = np.random.randn(10000, 3, 3).astype(np.float32)
    fully_inside = np.ones(10000, dtype=bool)

    t0 = time.time()
    for _ in range(1000):
        finite_orig = orig(screen)
    t1 = time.time()

    t2 = time.time()
    for _ in range(1000):
        finite_opt = opt(screen, fully_inside)
    t3 = time.time()

    print(f"Orig: {t1-t0:.4f}s")
    print(f"Opt:  {t3-t2:.4f}s")
    print(f"Match: {np.array_equal(finite_orig, finite_opt)}")

run_test()
