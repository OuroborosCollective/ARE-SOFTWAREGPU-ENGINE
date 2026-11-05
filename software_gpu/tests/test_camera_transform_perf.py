import time
import unittest
import numpy as np
from software_gpu.integrations.aurion.offline_lod_worker import _camera_transform

class TestCameraTransformPerf(unittest.TestCase):
    def test_perf(self):
        vertices = np.random.rand(100000, 3)
        config = {
            "yaw_degrees": 45,
            "pitch_degrees": 30,
            "center_y": 0,
            "x_half_extent": 10,
            "y_half_extent": 10
        }
        t0 = time.perf_counter()
        for _ in range(100):
            _camera_transform(vertices, config)
        t1 = time.perf_counter()
        elapsed = t1 - t0
        self.assertLess(elapsed, 15.0, "Performance optimization failed or too slow.")

if __name__ == '__main__':
    unittest.main()
