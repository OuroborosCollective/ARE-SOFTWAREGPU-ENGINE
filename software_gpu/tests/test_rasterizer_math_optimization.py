import unittest
from unittest import mock
import numpy as np
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Shader, Vertex

class TestRasterizerMathOptimization(unittest.TestCase):
    @mock.patch('numpy.floor')
    @mock.patch('numpy.ceil')
    def test_rasterizer_uses_math_instead_of_numpy(self, mock_ceil, mock_floor):
        fb = Framebuffer(100, 100)
        rasterizer = SoftwareRasterizer(fb, backend="bands")

        class DummyShader(Shader):
            def vertex_shader(self, vertex):
                return vertex.position, {}
            def fragment_shader(self, varyings):
                return (1.0, 1.0, 1.0, 1.0)

        shader = DummyShader()

        v0 = Vertex([10.0, 10.0, 0.5])
        v1 = Vertex([50.0, 10.0, 0.5])
        v2 = Vertex([30.0, 50.0, 0.5])

        rasterizer.draw_mesh([v0, v1, v2], [(0, 1, 2)], shader)

        mock_floor.assert_not_called()
        mock_ceil.assert_not_called()

if __name__ == '__main__':
    unittest.main()
