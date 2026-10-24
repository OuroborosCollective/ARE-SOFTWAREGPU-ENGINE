import time
import unittest
import numpy as np
from software_gpu.graphics.geometry import prepare_triangles
from software_gpu.graphics.shader import Vertex, BlinnPhongShader, Matrix4

class TestGeometryPerformance(unittest.TestCase):
    def test_prepare_triangles_performance_gate(self):
        """Ensures the optimized prepare_triangles remains fast without np.stack overhead."""
        N = 10000
        vertices = [
            Vertex(position=np.array([np.random.randn(), np.random.randn(), np.random.randn()]))
            for _ in range(N)
        ]
        indices = [(i, (i + 1) % N, (i + 2) % N) for i in range(N)]

        # Identity shader
        shader = BlinnPhongShader(
            model_matrix=Matrix4.identity(),
            view_matrix=Matrix4.translation(0, 0, -5),
            proj_matrix=Matrix4.perspective(np.pi / 4, 1.0, 0.1, 100.0)
        )

        # Warmup
        _ = prepare_triangles(vertices, indices[:100], shader, 1024, 1024)

        # Timing
        t0 = time.time()
        _ = prepare_triangles(vertices, indices, shader, 1024, 1024)
        elapsed = time.time() - t0

        # Strict gate for CI: The optimized function should process 10k triangles in <5.0s locally.
        # Using a generous threshold to avoid flakiness in slow CI environments while
        # still catching catastrophic O(N) regressions or accidental np.stack reversions.
        self.assertLess(elapsed, 5.0, "Geometry preparation took too long, possible performance regression!")

if __name__ == '__main__':
    unittest.main()
