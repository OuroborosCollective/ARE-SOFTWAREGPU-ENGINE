import unittest
import numpy as np
from software_gpu.graphics.geometry import is_top_left

class TestIsTopLeft(unittest.TestCase):
    def test_top_left(self):
        # Positive dy
        self.assertTrue(is_top_left(np.array([0, 0]), np.array([0, 1])))
        self.assertTrue(is_top_left(np.array([1, 1]), np.array([0, 2])))

        # Negative dy
        self.assertFalse(is_top_left(np.array([0, 1]), np.array([0, 0])))
        self.assertFalse(is_top_left(np.array([0, 2]), np.array([1, 1])))

        # Zero dy, negative dx
        self.assertTrue(is_top_left(np.array([1, 0]), np.array([0, 0])))
        self.assertTrue(is_top_left(np.array([2, 1]), np.array([1, 1])))

        # Zero dy, positive dx
        self.assertFalse(is_top_left(np.array([0, 0]), np.array([1, 0])))
        self.assertFalse(is_top_left(np.array([1, 1]), np.array([2, 1])))

if __name__ == '__main__':
    unittest.main()
