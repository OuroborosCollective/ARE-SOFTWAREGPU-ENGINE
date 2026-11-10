import unittest
from unittest import mock
import numpy as np

class TestPerformanceMathFloorCeil(unittest.TestCase):
    @mock.patch('numpy.floor')
    @mock.patch('numpy.ceil')
    def test_no_np_floor_ceil_rasterizer(self, mock_ceil, mock_floor):
        from software_gpu.graphics.rasterizer import SoftwareRasterizer
        from software_gpu.graphics.framebuffer import Framebuffer
        from software_gpu.graphics.shader import Shader, Vertex

        fb = Framebuffer(64, 64)
        rasterizer = SoftwareRasterizer(fb)

        class MockShader(Shader):
            def fragment_shader(self, varyings):
                return (1.0, 1.0, 1.0, 1.0)

            def vertex_shader(self, vertex):
                return vertex.position, {}

        shader = MockShader()
        v1 = Vertex(np.array([10.0, 10.0, 0.5, 1.0]), np.array([0, 0, 1.0]), np.array([0.0, 0.0]), np.array([1.0, 1.0, 1.0, 1.0]))
        v2 = Vertex(np.array([50.0, 10.0, 0.5, 1.0]), np.array([0, 0, 1.0]), np.array([1.0, 0.0]), np.array([1.0, 1.0, 1.0, 1.0]))
        v3 = Vertex(np.array([10.0, 50.0, 0.5, 1.0]), np.array([0, 0, 1.0]), np.array([0.0, 1.0]), np.array([1.0, 1.0, 1.0, 1.0]))

        rasterizer.draw_mesh([v1, v2, v3], [(0, 1, 2)], shader)

        mock_floor.assert_not_called()
        mock_ceil.assert_not_called()

    @mock.patch('numpy.floor')
    @mock.patch('numpy.ceil')
    def test_no_np_floor_ceil_postprocess(self, mock_ceil, mock_floor):
        from software_gpu.graphics.postprocess import MSAAFramebuffer, MSAARasterizer
        from software_gpu.graphics.shader import Shader, Vertex

        fb = MSAAFramebuffer(64, 64)
        rasterizer = MSAARasterizer(fb)

        class MockShader(Shader):
            def fragment_shader(self, varyings):
                return (1.0, 1.0, 1.0, 1.0)

            def vertex_shader(self, vertex):
                return vertex.position, {}

        shader = MockShader()
        v1 = Vertex(np.array([10.0, 10.0, 0.5, 1.0]), np.array([0, 0, 1.0]), np.array([0.0, 0.0]), np.array([1.0, 1.0, 1.0, 1.0]))
        v2 = Vertex(np.array([50.0, 10.0, 0.5, 1.0]), np.array([0, 0, 1.0]), np.array([1.0, 0.0]), np.array([1.0, 1.0, 1.0, 1.0]))
        v3 = Vertex(np.array([10.0, 50.0, 0.5, 1.0]), np.array([0, 0, 1.0]), np.array([0.0, 1.0]), np.array([1.0, 1.0, 1.0, 1.0]))

        rasterizer.draw_mesh([v1, v2, v3], [(0, 1, 2)], shader)

        mock_floor.assert_not_called()
        mock_ceil.assert_not_called()

    @mock.patch('numpy.floor')
    @mock.patch('numpy.ceil')
    def test_no_np_floor_ceil_tile_backend(self, mock_ceil, mock_floor):
        from software_gpu.graphics.tile_backend import rasterize_tiles
        from software_gpu.graphics.framebuffer import Framebuffer
        from software_gpu.graphics.shader import Shader
        from concurrent.futures import ThreadPoolExecutor

        fb = Framebuffer(64, 64)

        class MockShader(Shader):
            def fragment_shader(self, varyings):
                return (1.0, 1.0, 1.0, 1.0)

            def vertex_shader(self, vertex):
                return vertex.position, {}

        shader = MockShader()
        s0 = np.array([10.0, 10.0, 0.5, 1.0])
        s1 = np.array([50.0, 10.0, 0.5, 1.0])
        s2 = np.array([10.0, 50.0, 0.5, 1.0])
        triangles = [(s0, s1, s2, 1.0, 1.0, 1.0, {}, {}, {}, 10.0)]

        with ThreadPoolExecutor(max_workers=1) as executor:
            rasterize_tiles(fb, triangles, shader, 16, executor, 1, compiled=False, planned=False, plan_policy=None, prepared_bins=None)

        mock_floor.assert_not_called()
        mock_ceil.assert_not_called()

if __name__ == '__main__':
    unittest.main()
