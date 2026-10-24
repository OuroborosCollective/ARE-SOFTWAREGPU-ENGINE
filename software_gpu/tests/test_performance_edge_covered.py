import unittest
import time
import numpy as np
from software_gpu.graphics.geometry import prepare_triangles
from software_gpu.graphics.shader import Matrix4, BlinnPhongShader, Vertex

class TestGeometryPerformanceGate(unittest.TestCase):
    def test_prepare_triangles_performance_gate(self):
        """
        CI Test Gate: Ensures that `prepare_triangles` runs efficiently by avoiding
        slow `np.stack` allocations and reductions in the hot path.
        """
        # Create a large mock mesh to stress the setup phase
        num_vertices = 20000
        num_faces = 30000
        np.random.seed(42)
        vertices = [Vertex(pos) for pos in np.random.rand(num_vertices, 3)]
        indices = np.random.randint(0, num_vertices, (num_faces, 3))

        model = Matrix4.identity()
        view = Matrix4.identity()
        proj = Matrix4.perspective(np.radians(60), 1.0, 0.1, 100.0)
        shader = BlinnPhongShader(model, view, proj)

        start = time.time()
        res = prepare_triangles(vertices, indices, shader, 800, 600)
        end = time.time()

        elapsed = end - start

        # In a CI environment, a generous threshold is used to prevent flakiness
        # while still catching massive performance regressions (e.g. going back to np.stack).
        # On slower CI runners, this can take up to 3 seconds even with optimizations.
        # We allow 4.0s to ensure it passes reliably while still guarding against
        # O(N^2) or massive regressions.
        self.assertLess(elapsed, 4.0, f"Performance regression detected in prepare_triangles: took {elapsed}s")

if __name__ == '__main__':
    unittest.main()
