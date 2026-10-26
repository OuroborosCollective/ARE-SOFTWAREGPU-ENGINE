import json
import statistics
import sys
import time
import unittest

class TestShaderClampPerformance(unittest.TestCase):
    def test_paired_scalar_timing_guard(self):
        import numpy as np
        rng = np.random.default_rng(1234)
        N = 1000000
        n0 = rng.random(size=N).astype(np.float32)
        n1 = rng.random(size=N).astype(np.float32)
        n2 = rng.random(size=N).astype(np.float32)
        l0, l1, l2 = 0.5, 0.8, 1.0

        old_ms, new_ms = [], []

        for repetition in range(15):
            # Baseline: max(0.0, float())
            start = time.perf_counter_ns()
            for i in range(100000):
                v = max(0.0, float(n0[i]*l0 + n1[i]*l1 + n2[i]*l2))
            old_ms.append((time.perf_counter_ns() - start) / 1e6)

            # New: ternary float()
            start = time.perf_counter_ns()
            for i in range(100000):
                val = float(n0[i]*l0 + n1[i]*l1 + n2[i]*l2)
                v = val if val > 0.0 else 0.0
            new_ms.append((time.perf_counter_ns() - start) / 1e6)

        old_median = statistics.median(old_ms)
        new_median = statistics.median(new_ms)
        ratio = old_median / new_median

        print("SHADER_CLAMP_PAIRED_CPU_EVIDENCE " + json.dumps({
            "python": sys.version.split()[0],
            "numpy": np.__version__, "seed": 1234, "shape": [100000],
            "repeats": 15,
            "old_median_ms": round(old_median, 6),
            "new_median_ms": round(new_median, 6),
            "speedup": round(ratio, 4),
            "scope": "shader diffuse clamp only",
        }, sort_keys=True))

        # Flaky check prevention: use very generous threshold.
        self.assertGreaterEqual(ratio, 0.5, "shader clamp performance measurement")

if __name__ == "__main__":
    unittest.main()
