import unittest
import time
import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex
from software_gpu.tests.test_raster_correctness_contract import FlatColorShader

class TestArrayUnrollPerformance(unittest.TestCase):
    def test_array_unroll_is_fast(self):
        # We need a large quad to ensure the inner loop processes many pixels
        near_l = (-0.9, -0.9, 0.5, 1.0)
        near_r = (0.9, -0.9, 0.5, 1.0)
        far_l = (-0.9, 0.9, 0.5, 1.0)
        far_r = (0.9, 0.9, 0.5, 1.0)
        verts = [
            Vertex(np.array(near_l, dtype=np.float64), color=np.array([1., 0., 0.])),
            Vertex(np.array(near_r, dtype=np.float64), color=np.array([1., 0., 0.])),
            Vertex(np.array(far_l, dtype=np.float64), color=np.array([1., 0., 0.])),
            Vertex(np.array(far_r, dtype=np.float64), color=np.array([1., 0., 0.])),
        ]
        faces = [(0, 1, 2), (1, 3, 2)]

        fb = Framebuffer(512, 512)
        fb.clear(16, 25, 38, 255, depth=1.0)
        rasterizer = SoftwareRasterizer(fb, backend="bands", num_threads=1, tile_size=16)

        # Warmup
        rasterizer.draw_mesh(verts, faces, FlatColorShader())

        # Timing execution
        start = time.perf_counter()
        # Drawing 5 times to amplify the measurement for the test limit
        for _ in range(5):
            rasterizer.draw_mesh(verts, faces, FlatColorShader())
        duration = time.perf_counter() - start
        rasterizer.executor.shutdown(wait=True)

        # Assert generous threshold since CI execution varies in speed
        self.assertLess(duration, 25.0, "Rasterization using the unrolled array optimization should be fast")

if __name__ == '__main__':
    unittest.main()
