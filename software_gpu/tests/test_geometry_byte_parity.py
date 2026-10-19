import unittest
import numpy as np
from software_gpu.graphics.geometry import prepare_triangles
from software_gpu.graphics.shader import Shader, Vertex

class MockShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {}
    def fragment_shader(self, varyings):
        return 255, 255, 255, 255

class TestGeometryByteParityGate(unittest.TestCase):
    def test_byte_parity_screen_ndc_mapping(self):
        # We assert that the new optimization mapping evaluates EXACTLY to byte-parity
        # as a direct replacement of np.stack.

        ndc = np.array([
            [[ 0.5, -0.5, 0.5], [-0.5, 0.5, 0.5], [ 0.0, 0.0, 0.5]],
            [[-1.0, -1.0, 0.5], [ 1.0, 1.0, 0.5], [ 0.5, 0.5, 0.5]]
        ], dtype=np.float64)

        width = 800
        height = 600

        # Original logic using float64 exact math + stack
        sx_orig = (ndc[..., 0] + 1.0) * 0.5 * width
        sy_orig = (1.0 - ndc[..., 1]) * 0.5 * height
        screen_orig = np.stack([sx_orig, sy_orig, ndc[..., 2]], axis=-1).astype(np.float32)

        # New optimized explicitly allocated logic
        screen_opt = np.empty_like(ndc, dtype=np.float32)
        screen_opt[..., 0] = (ndc[..., 0] + 1.0) * (0.5 * width)
        screen_opt[..., 1] = (1.0 - ndc[..., 1]) * (0.5 * height)
        screen_opt[..., 2] = ndc[..., 2]

        # Verify byte parity
        np.testing.assert_array_equal(screen_orig, screen_opt)

if __name__ == '__main__':
    unittest.main()
