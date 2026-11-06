import time
import unittest
import math
import numpy as np

class TestRasterLoopPerformance(unittest.TestCase):
    def test_inline_ternary_min_max_is_fast(self):
        s00, s10, s20 = 1.2, 5.3, 0.4

        def baseline(s00, s10, s20):
            return int(np.floor(min(s00, s10, s20)))

        def optimized(s00, s10, s20):
            min_x = s00 if s00 < s10 else s10
            min_x = min_x if min_x < s20 else s20
            return int(math.floor(min_x))

        start = time.perf_counter()
        for _ in range(100000):
            baseline(s00, s10, s20)
        baseline_time = time.perf_counter() - start

        start = time.perf_counter()
        for _ in range(100000):
            optimized(s00, s10, s20)
        optimized_time = time.perf_counter() - start

        # Ensure optimized is faster, add a very small tolerance for timing fluctuations
        self.assertLess(optimized_time, baseline_time + 0.05)

if __name__ == "__main__":
    unittest.main()
