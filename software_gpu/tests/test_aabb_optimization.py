import unittest
import numpy as np
import math
from unittest import mock

class TestAABBOptimization(unittest.TestCase):
    def test_aabb_parity(self):
        rng = np.random.default_rng(42)
        for _ in range(1000):
            s0 = rng.uniform(-100, 100, 3)
            s1 = rng.uniform(-100, 100, 3)
            s2 = rng.uniform(-100, 100, 3)

            orig = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))

            m_x0 = s1[0] if s1[0] < s2[0] else s2[0]
            m_min_x = math.floor(s0[0] if s0[0] < m_x0 else m_x0)
            opt = m_min_x if m_min_x > 0 else 0

            self.assertEqual(orig, opt)

if __name__ == "__main__":
    unittest.main()
