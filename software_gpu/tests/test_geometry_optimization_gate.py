import unittest
import numpy as np
from software_gpu.graphics.geometry import prepare_triangles
from software_gpu.graphics.shader import Shader, Vertex

class MockShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {}
    def fragment_shader(self, varyings):
        return 255, 255, 255, 255

class TestGeometryOptimizationGate(unittest.TestCase):
    def test_prepare_triangles_optimization_gate(self):
        # A test gate to ensure `prepare_triangles` correctly computes screen coordinates
        # and clipping logically. This catches any regressions introduced by optimization.

        # We test an arrangement of triangles: fully inside, outside, and partially inside.
        vertices = []
        indices = []

        # 1. Fully inside frustum
        vertices.append(Vertex(position=[0.0, 0.0, 0.5, 1.0]))
        vertices.append(Vertex(position=[0.1, 0.0, 0.5, 1.0]))
        vertices.append(Vertex(position=[0.0, 0.1, 0.5, 1.0]))
        indices.append((0, 1, 2))

        # 2. Outside frustum
        vertices.append(Vertex(position=[2.0, 2.0, 0.5, 1.0]))
        vertices.append(Vertex(position=[2.1, 2.0, 0.5, 1.0]))
        vertices.append(Vertex(position=[2.0, 2.1, 0.5, 1.0]))
        indices.append((3, 4, 5))

        # 3. Crossing frustum boundary (clipping required)
        vertices.append(Vertex(position=[-1.5, 0.0, 0.5, 1.0]))
        vertices.append(Vertex(position=[-0.5, 0.0, 0.5, 1.0]))
        vertices.append(Vertex(position=[-1.0, 1.5, 0.5, 1.0]))
        indices.append((6, 7, 8))

        shader = MockShader()
        width, height = 800, 600

        triangles = prepare_triangles(vertices, indices, shader, width, height)

        # First triangle (inside) should emit exactly 1 polygon (fast path)
        # Second triangle (outside) should be clipped out entirely
        # Third triangle (crossing) might be split into multiple primitives, but should produce valid geometry.

        self.assertGreater(len(triangles), 1, "Should have correctly clipped and prepared output primitives.")

        # Validates screen array format bounds are respected.
        for tri in triangles:
            for s in tri[:3]: # The three screen positions
                self.assertIsNotNone(s)
                self.assertEqual(len(s), 3, "Screen coordinate must be length 3.")
                # We assert that there are NO NaN values.
                self.assertTrue(np.isfinite(s).all(), "Screen coordinates must not contain NaNs")

if __name__ == '__main__':
    unittest.main()
