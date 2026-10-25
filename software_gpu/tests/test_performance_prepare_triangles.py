import unittest
import time
import numpy as np

from software_gpu.graphics.geometry import prepare_triangles

class MockShader:
    def vertex_shader(self, vertex):
        return vertex[0], {"color": np.array([1.0, 1.0, 1.0])}

class TestPrepareTrianglesPerformance(unittest.TestCase):
    def test_fully_inside_performance_gate(self):
        """
        Ensures prepare_triangles executes within the expected fast path threshold.
        """
        F = 10000
        vertices = []
        indices = []
        for i in range(F):
            # Triangle that fits fully inside
            w = 10.0
            p1 = np.array([0.1, 0.1, 0.5, w])
            p2 = np.array([0.5, 0.1, 0.5, w])
            p3 = np.array([0.1, 0.5, 0.5, w])

            base = i * 3
            vertices.append((p1, None))
            vertices.append((p2, None))
            vertices.append((p3, None))
            indices.append([base, base + 1, base + 2])

        shader = MockShader()

        # Warmup and measurement
        times = []
        for _ in range(5):
            t0 = time.time()
            res = prepare_triangles(vertices, indices, shader, 800, 600)
            t1 = time.time()
            times.append(t1 - t0)

        best_time = min(times)
        # 2.5s is a generous threshold for 10000 triangles setup to prevent CI flakiness,
        self.assertLess(best_time, 2.5, f"prepare_triangles calc too slow: {best_time:.4f}s")
        self.assertGreaterEqual(best_time, 0.0, "time must be positive")
        self.assertEqual(len(res), F)

if __name__ == "__main__":
    unittest.main()
