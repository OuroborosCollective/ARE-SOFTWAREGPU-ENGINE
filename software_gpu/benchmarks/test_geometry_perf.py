import numpy as np
import time

def benchmark_old_geometry(F, width, height, iterations=1000):
    fpos = np.random.rand(F, 3, 4)
    w = fpos[..., 3]
    inv_w = 1.0 / w
    ndc = fpos[..., :3] * inv_w[..., None]

    t0 = time.time()
    for _ in range(iterations):
        sx = (ndc[..., 0] + 1.0) * 0.5 * width
        sy = (1.0 - ndc[..., 1]) * 0.5 * height
        screen = np.stack([sx, sy, ndc[..., 2]], axis=-1).astype(np.float32)
        finite = np.isfinite(screen).all(axis=(1, 2))
        area = ((screen[:, 2, 0] - screen[:, 0, 0]) * (screen[:, 1, 1] - screen[:, 0, 1])
                - (screen[:, 2, 1] - screen[:, 0, 1]) * (screen[:, 1, 0] - screen[:, 0, 0]))
    t1 = time.time()
    return t1 - t0

def benchmark_new_geometry(F, width, height, iterations=1000):
    fpos = np.random.rand(F, 3, 4)
    w = fpos[..., 3]
    inv_w = 1.0 / w
    ndc = fpos[..., :3] * inv_w[..., None]

    t0 = time.time()
    for _ in range(iterations):
        sx = (ndc[..., 0] + 1.0) * 0.5 * width
        sy = (1.0 - ndc[..., 1]) * 0.5 * height
        shape = sx.shape
        screen = np.empty(shape + (3,), dtype=np.float32)
        screen[..., 0] = sx
        screen[..., 1] = sy
        screen[..., 2] = ndc[..., 2]
        finite = np.isfinite(screen).all(axis=(1, 2))
        sx32 = sx.astype(np.float32)
        sy32 = sy.astype(np.float32)
        area = ((sx32[:, 2] - sx32[:, 0]) * (sy32[:, 1] - sy32[:, 0])
                - (sy32[:, 2] - sy32[:, 0]) * (sx32[:, 1] - sx32[:, 0]))
    t1 = time.time()
    return t1 - t0

if __name__ == '__main__':
    old_time = benchmark_old_geometry(1000, 800, 600)
    new_time = benchmark_new_geometry(1000, 800, 600)
    print(f"Old approach time: {old_time:.4f} seconds")
    print(f"New approach time: {new_time:.4f} seconds")
    print(f"Speedup: {old_time / new_time:.2f}x")
