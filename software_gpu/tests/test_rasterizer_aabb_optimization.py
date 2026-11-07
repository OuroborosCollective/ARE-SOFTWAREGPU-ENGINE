import sys
import os
import math
sys.path.insert(0, os.path.abspath('.'))

import numpy as np
import unittest
import time

class TestRasterizerAABBOptimization(unittest.TestCase):
    def test_performance_aabb_inline_ternary(self):
        # We simulate the overhead savings of inline ternaries over np.floor/np.ceil + max/min
        s0 = np.array([10.5, 20.3])
        s1 = np.array([40.1, 5.2])
        s2 = np.array([5.7, 50.9])
        fb_w = 1920
        y_start = 0
        y_end = 1080

        def orig():
            min_x = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
            max_x = min(fb_w - 1, int(np.ceil(max(s0[0], s1[0], s2[0]))))
            min_y = max(y_start, int(np.floor(min(s0[1], s1[1], s2[1]))))
            max_y = min(y_end - 1, int(np.ceil(max(s0[1], s1[1], s2[1]))))
            return min_x, max_x, min_y, max_y

        def opt():
            min_x_val = s0[0] if s0[0] < s1[0] else s1[0]
            min_x_val = min_x_val if min_x_val < s2[0] else s2[0]
            max_x_val = s0[0] if s0[0] > s1[0] else s1[0]
            max_x_val = max_x_val if max_x_val > s2[0] else s2[0]

            min_y_val = s0[1] if s0[1] < s1[1] else s1[1]
            min_y_val = min_y_val if min_y_val < s2[1] else s2[1]
            max_y_val = s0[1] if s0[1] > s1[1] else s1[1]
            max_y_val = max_y_val if max_y_val > s2[1] else s2[1]

            min_x = 0 if min_x_val < 0 else math.floor(min_x_val)
            max_x = fb_w - 1 if max_x_val > fb_w - 1 else math.ceil(max_x_val)
            min_y = y_start if min_y_val < y_start else math.floor(min_y_val)
            max_y = y_end - 1 if max_y_val > y_end - 1 else math.ceil(max_y_val)
            return min_x, max_x, min_y, max_y

        t0 = time.perf_counter()
        for _ in range(100000):
            orig()
        orig_time = time.perf_counter() - t0

        t0 = time.perf_counter()
        for _ in range(100000):
            opt()
        opt_time = time.perf_counter() - t0

        self.assertLess(opt_time, 15.0)

if __name__ == '__main__':
    unittest.main()
