import unittest
import time
import numpy as np
import math

class TestRasterizerMath(unittest.TestCase):
    def test_math_floor_parity(self):
        vals = [1.2, -1.2, 0.0, 5.0, 5.9, -5.9, 100.1, -100.1]
        for v in vals:
            np_res = int(np.floor(v))
            math_res = math.floor(v)
            self.assertEqual(np_res, math_res, f"Failed on {v}")

    def test_math_ceil_parity(self):
        vals = [1.2, -1.2, 0.0, 5.0, 5.9, -5.9, 100.1, -100.1]
        for v in vals:
            np_res = int(np.ceil(v))
            math_res = math.ceil(v)
            self.assertEqual(np_res, math_res, f"Failed on {v}")

    def test_math_floor_performance(self):
        v = 1.2
        start = time.perf_counter()
        for _ in range(100000):
            _ = math.floor(v)
        elapsed_time = time.perf_counter() - start
        self.assertLess(elapsed_time, 0.5)

if __name__ == '__main__':
    unittest.main()
