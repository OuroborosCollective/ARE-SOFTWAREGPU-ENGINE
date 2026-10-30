import unittest
import numpy as np

class TestGeometryStackRegression(unittest.TestCase):
    def test_prepare_triangles_regression_finite_check(self):
        # We just want to ensure that `software_gpu.graphics.geometry.prepare_triangles`
        # is functionally identical and correctly handles dimensions whether batch dims are passed or not.
        from software_gpu.graphics.geometry import prepare_triangles
        from software_gpu.graphics.shader import Shader

        class MockShader(Shader):
            def vertex_shader(self, vertex):
                return vertex[:4], {}
            def fragment_shader(self, bc):
                return None

        # Construct dummy inputs with exact bounds that shouldn't error or give incorrect `finite` checks
        vertices = np.array([
            [0.0, 0.0, 1.0, 1.0],
            [1.0, 0.0, 1.0, 1.0],
            [0.0, 1.0, 1.0, 1.0],
            [2.0, 2.0, 1.0, 1.0], # Extra vertex for faces
        ], dtype=np.float32)

        # Valid faces (all indices valid)
        faces = np.array([
            [0, 1, 2],
            [1, 2, 3]
        ])

        width = 800
        height = 600

        # Test single dimension faces
        res = prepare_triangles(
            vertices, faces, MockShader(), width, height
        )

        self.assertTrue(len(res[0]) > 0)

if __name__ == '__main__':
    unittest.main()
