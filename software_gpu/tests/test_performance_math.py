import unittest
import math
import time
import numpy as np

class TestMathFloorPerformance(unittest.TestCase):
    def test_math_floor_performance(self):
        """
        Verify that replacing int(np.floor()) with math.floor() on primitive scalars
        is measurably faster by avoiding function call/dispatch overhead and array allocations.
        """
        s0 = np.array([1.5, 2.5, 3.5])
        s1 = np.array([10.1, -5.5, 3.3])
        s2 = np.array([-3.2, 8.8, 12.1])
        min_x = 0
        start = time.perf_counter()
        for _ in range(100000):
            min_x = max(0, math.floor(min(s0[0], s1[0], s2[0])))
            max_x = min(100, math.ceil(max(s0[0], s1[0], s2[0])))
            min_y = max(0, math.floor(min(s0[1], s1[1], s2[1])))
            max_y = min(100, math.ceil(max(s0[1], s1[1], s2[1])))
        end = time.perf_counter()
        elapsed = end - start

        # We also benchmark the old way to assert speedup is strictly better
        start_old = time.perf_counter()
        for _ in range(100000):
            min_x = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
            max_x = min(100, int(np.ceil(max(s0[0], s1[0], s2[0]))))
            min_y = max(0, int(np.floor(min(s0[1], s1[1], s2[1]))))
            max_y = min(100, int(np.ceil(max(s0[1], s1[1], s2[1]))))
        end_old = time.perf_counter()
        elapsed_old = end_old - start_old

        print(f"\nmath.floor elapsed: {elapsed:.4f}s")
        print(f"int(np.floor) elapsed: {elapsed_old:.4f}s")

        self.assertLess(elapsed, 15.0)
        # Using a very generous multiplier (like math being faster than 1.05x the old method)
        # However, due to CI variability, we simply assert it runs under a threshold.
        # But we do assert that the standard library math module is strictly faster.
        self.assertLess(elapsed, elapsed_old)

if __name__ == '__main__':
    unittest.main()
