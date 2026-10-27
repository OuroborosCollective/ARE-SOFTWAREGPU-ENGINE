import numpy as np

def run_test():
    # Mock data
    fpos = np.random.randn(10, 3, 4).astype(np.float64)
    fpos[..., 3] = np.abs(fpos[..., 3]) + 0.1 # w > 0
    w = fpos[..., 3]
    inv_w = 1.0 / w
    ndc = fpos[..., :3] * inv_w[..., None]
    width = 800
    height = 600
    sx = (ndc[..., 0] + 1.0) * 0.5 * width
    sy = (1.0 - ndc[..., 1]) * 0.5 * height

    # Original
    screen_orig = np.stack([sx, sy, ndc[..., 2]], axis=-1).astype(np.float32)
    finite_orig = np.isfinite(screen_orig).all(axis=(1, 2))

    # Optimized
    screen_opt = np.empty(ndc.shape[:-1] + (3,), dtype=np.float32)
    screen_opt[..., 0] = sx
    screen_opt[..., 1] = sy
    screen_opt[..., 2] = ndc[..., 2]

    # We need a fully_inside array for the opt version
    fully_inside = np.ones(fpos.shape[0], dtype=bool)
    finite_opt = fully_inside.copy()
    for v in range(3):
        for c in range(3):
            np.logical_and(finite_opt, np.isfinite(screen_opt[..., v, c]), out=finite_opt)

    print("Screen matches:", np.allclose(screen_orig, screen_opt))
    print("Finite matches:", np.array_equal(finite_orig, finite_opt))

run_test()
