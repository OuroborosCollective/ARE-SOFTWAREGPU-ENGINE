"""Ensure homogeneous clipping-plane distance keeps the old evaluation order."""
import unittest

import numpy as np

from software_gpu.graphics.geometry import _distance


class DistanceIndexParityTest(unittest.TestCase):
    def test_seeded_float32_and_float64_exact_clipping_distances(self):
        rng = np.random.default_rng(137055705)
        for dtype in (np.float32, np.float64):
            for vec in rng.uniform(-100, 100, (256, 4)).astype(dtype):
                x, y, z, w = vec
                expected = (w + x, w - x, w + y, w - y, w + z, w - z)
                for plane, want in enumerate(expected):
                    got = _distance(vec, plane)
                    self.assertEqual(got, want)
                    self.assertEqual(type(got), type(want))
                # The last plane is the existing min-W clipping guard.
                # Check that unsupported plane index routes there unchanged.
                self.assertEqual(_distance(vec, 6), _distance(vec, 99))


if __name__ == "__main__":
    unittest.main()
