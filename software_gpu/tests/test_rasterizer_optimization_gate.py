import unittest
from unittest.mock import patch
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Shader

class DummyShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {}
    def fragment_shader(self, varyings):
        return 255, 255, 255, 255

class TestRasterizerOptimization(unittest.TestCase):
    def test_no_numpy_floor_ceil_in_hotpath(self):
        fb = Framebuffer(32, 32)
        rasterizer = SoftwareRasterizer(fb, backend="bands", num_threads=1)

        s0 = (0.0, 0.0, 0.5)
        s1 = (10.0, 0.0, 0.5)
        s2 = (0.0, 10.0, 0.5)
        inv_w0, inv_w1, inv_w2 = 1.0, 1.0, 1.0
        v0_var, v1_var, v2_var = {}, {}, {}
        area = 50.0

        triangles = [(s0, s1, s2, inv_w0, inv_w1, inv_w2, v0_var, v1_var, v2_var, area)]
        shader = DummyShader()

        with patch('numpy.floor') as mock_floor, patch('numpy.ceil') as mock_ceil:
            rasterizer._rasterize_band(triangles, shader, 0, 32)

            mock_floor.assert_not_called()
            mock_ceil.assert_not_called()

if __name__ == '__main__':
    unittest.main()
