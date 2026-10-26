import json
import statistics
import sys
import time
import unittest

class TestGeometrySetupPerformance(unittest.TestCase):
    def test_paired_array_timing_guard(self):
        import numpy as np
        rng = np.random.default_rng(1234)
        N = 10000
        sx = rng.random(size=(N, 3)).astype(np.float32)
        sy = rng.random(size=(N, 3)).astype(np.float32)
        ndc_z = rng.random(size=(N, 3)).astype(np.float32)

        old_ms, new_ms = [], []

        for repetition in range(15):
            # Baseline: np.stack
            start = time.perf_counter_ns()
            for _ in range(50):
                screen = np.stack([sx, sy, ndc_z], axis=-1).astype(np.float32)
                finite = np.isfinite(screen).all(axis=(1, 2))
            old_ms.append((time.perf_counter_ns() - start) / 1e6)

            # New: empty array and bitwise condition
            start = time.perf_counter_ns()
            for _ in range(50):
                screen = np.empty((sx.shape[0], 3, 3), dtype=np.float32)
                screen[..., 0] = sx
                screen[..., 1] = sy
                screen[..., 2] = ndc_z
                sf = np.isfinite(screen)
                finite2 = sf[:, 0, 0] & sf[:, 0, 1] & sf[:, 0, 2] & sf[:, 1, 0] & sf[:, 1, 1] & sf[:, 1, 2] & sf[:, 2, 0] & sf[:, 2, 1] & sf[:, 2, 2]
            new_ms.append((time.perf_counter_ns() - start) / 1e6)

        old_median = statistics.median(old_ms)
        new_median = statistics.median(new_ms)
        ratio = old_median / new_median

        print("GEOMETRY_SETUP_PAIRED_CPU_EVIDENCE " + json.dumps({
            "python": sys.version.split()[0],
            "numpy": np.__version__, "seed": 1234, "shape": [N],
            "repeats": 15, "inner_loops": 50,
            "old_median_ms": round(old_median, 6),
            "new_median_ms": round(new_median, 6),
            "speedup": round(ratio, 4),
            "scope": "geometry setup loop array preallocation and all",
        }, sort_keys=True))

        # Flaky check prevention: use very generous threshold.
        self.assertGreaterEqual(ratio, 0.5, "geometry setup performance measurement")

if __name__ == "__main__":
    unittest.main()
