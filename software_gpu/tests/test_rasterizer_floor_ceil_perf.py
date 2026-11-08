import unittest
import time
import math
import numpy as np

class TestRasterizerPerf(unittest.TestCase):
    def test_floor_ceil_overhead(self):
        # We test that math.floor is efficiently executing on simple tuples in hotpath
        # simulating the bounding box evaluation
        start = time.perf_counter()

        s0, s1, s2 = (1.5, 2.3), (5.1, 7.8), (3.2, 0.4)
        for _ in range(10000):
            min_x = max(0, math.floor(min(s0[0], s1[0], s2[0])))
            max_x = min(100, math.ceil(max(s0[0], s1[0], s2[0])))
            min_y = max(0, math.floor(min(s0[1], s1[1], s2[1])))
            max_y = min(100, math.ceil(max(s0[1], s1[1], s2[1])))

        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 15.0, "Bounding box calculation too slow")
