import unittest
from unittest import mock
import numpy as np
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Shader

class DummyShader(Shader):
    def fragment_shader(self, varyings):
        return (255, 0, 0, 255)

class TestRasterizerOptimization(unittest.TestCase):
    @mock.patch('numpy.floor')
    @mock.patch('numpy.ceil')
    def test_rasterizer_avoids_numpy_rounding(self, mock_ceil, mock_floor):
        fb = Framebuffer(64, 64)
        rasterizer = SoftwareRasterizer(fb, backend="bands")
        shader = DummyShader()

        triangles = [
            ([10.5, 10.2, 0.5], [50.8, 10.3, 0.5], [30.1, 50.9, 0.5],
             1.0, 1.0, 1.0, {}, {}, {}, 100.0)
        ]

        rasterizer._rasterize_band(triangles, shader, 0, 64)

        mock_floor.assert_not_called()
        mock_ceil.assert_not_called()

if __name__ == '__main__':
    unittest.main()
