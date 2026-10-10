import unittest
import time
import numpy as np
from software_gpu.graphics.geometry import edge_covered, is_top_left

def old_edge_covered(value, a, b):
    return (value > 0) | ((value == 0) & is_top_left(a, b))

class TestEdgeCoveredPerformance(unittest.TestCase):
    def test_edge_covered_performance(self):
        val = np.random.randn(1000, 1000)
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 1.0])

        start_old = time.time()
        for _ in range(100):
            old_edge_covered(val, a, b)
        old_time = time.time() - start_old

        start_new = time.time()
        for _ in range(100):
            edge_covered(val, a, b)
        new_time = time.time() - start_new

        self.assertLess(new_time, old_time)
        print(f"\nOld edge_covered time: {old_time:.4f}s")
        print(f"New edge_covered time: {new_time:.4f}s")
        print(f"Speedup: {old_time / new_time:.2f}x")

if __name__ == "__main__":
    unittest.main()
