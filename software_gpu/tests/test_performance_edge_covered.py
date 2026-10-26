import unittest
import numpy as np
import time
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.geometry import prepare_triangles

class DummyShader:
    def vertex_shader(self, vertex):
        return vertex[0], vertex[1]

class TestPerformanceOptimizations(unittest.TestCase):
    def test_framebuffer_clear_regression_overflow(self):
        # When clear is called with high RGBA values, if int casting isn't done correctly
        # an overflow or silent truncation could happen on 32-bit platforms.
        fb = Framebuffer(10, 10)
        fb.clear(r=255, g=255, b=255, a=255)
        # Verify color is white and not rolled over
        self.assertTrue((fb.color_buffer[0, 0] == [255, 255, 255, 255]).all())

    def test_prepare_triangles_performance_gate(self):
        # A simple performance proof gate for the geometry unrolling logic.
        shader = DummyShader()

        # Create a few hundred dummy vertices
        N = 500
        vertices = [ (np.random.rand(4), {}) for _ in range(N) ]
        for v in vertices:
            v[0][3] = 1.0 # Set w to 1
        indices = np.random.randint(0, N, size=(300, 3))

        start = time.perf_counter()
        res = prepare_triangles(vertices, indices, shader, 1024, 1024)
        end = time.perf_counter()

        # The time elapsed must be very small. A lenient bound to prevent CI flakiness.
        self.assertTrue((end - start) >= 0)
        self.assertTrue((end - start) < 0.5)

if __name__ == '__main__':
    unittest.main()
