import time
import unittest
import numpy as np
from software_gpu.graphics.geometry import _distance

class TestDistancePerformance(unittest.TestCase):
    def test_distance_unpacking_overhead(self):
        position = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        start = time.perf_counter()
        for _ in range(500000):
            _distance(position, 0)
            _distance(position, 1)
            _distance(position, 2)
            _distance(position, 3)
            _distance(position, 4)
            _distance(position, 5)
        elapsed = time.perf_counter() - start
        # Very generous threshold of 15.0s to avoid test flakiness in slow CI environments
        self.assertLess(elapsed, 15.0, "The _distance function is too slow. Ensure you are not unpacking the position tuple.")

if __name__ == '__main__':
    unittest.main()
