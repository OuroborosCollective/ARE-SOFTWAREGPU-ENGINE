import unittest
import time
import numpy as np
from software_gpu.graphics.geometry import prepare_triangles

class DummyShader:
    def vertex_shader(self, v):
        return v[0], {'color': np.array([1., 1., 1.])}

class TestPrepareTrianglesPerformance(unittest.TestCase):
    def test_prepare_triangles_performance(self):
        # We test that running prepare triangles is performant and doesn't run into a bottleneck
        # due to `np.stack` and boolean reductions in distance calculations.
        shader = DummyShader()

        N_VERTS = 10000
        N_FACES = 20000
        vertices = []
        for _ in range(N_VERTS):
            v = np.random.rand(4) * 2 - 1
            v[3] = np.abs(v[3]) + 1.0
            vertices.append((v, None))

        indices = np.random.randint(0, N_VERTS, size=(N_FACES, 3))

        start = time.perf_counter()
        prepare_triangles(vertices, indices, shader, 800, 600)
        elapsed = time.perf_counter() - start

        # A generous time threshold of 5.0s should suffice
        self.assertLess(elapsed, 5.0, "Performance degradation detected: prepare_triangles took too long")

if __name__ == "__main__":
    unittest.main()
