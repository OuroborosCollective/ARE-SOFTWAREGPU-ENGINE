import unittest
import time
import math
import numpy as np
import random

class TestPerformanceMathFloor(unittest.TestCase):
    def test_math_floor_performance(self):
        s0 = [random.uniform(0, 1000) for _ in range(3)]
        s1 = [random.uniform(0, 1000) for _ in range(3)]
        s2 = [random.uniform(0, 1000) for _ in range(3)]
        fb_w = 1000
        y_start = 0

        # Time math.floor vs np.floor
        t0 = time.time()
        for _ in range(100000):
            min_x = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
            max_x = min(fb_w - 1, int(np.ceil(max(s0[0], s1[0], s2[0]))))
            min_y = max(y_start, int(np.floor(min(s0[1], s1[1], s2[1]))))
            max_y = min(fb_w - 1, int(np.ceil(max(s0[1], s1[1], s2[1]))))
        t1 = time.time()

        t2 = time.perf_counter()
        for _ in range(100000):
            min_x = max(0, math.floor(min(s0[0], s1[0], s2[0])))
            max_x = min(fb_w - 1, math.ceil(max(s0[0], s1[0], s2[0])))
            min_y = max(y_start, math.floor(min(s0[1], s1[1], s2[1])))
            max_y = min(fb_w - 1, math.ceil(max(s0[1], s1[1], s2[1])))
        t3 = time.perf_counter()

        # Test performance gate (math.floor must be reasonably fast, e.g. < 1.0s for 100k loops)
        self.assertLess(t3 - t2, 1.0)

if __name__ == '__main__':
    unittest.main()
