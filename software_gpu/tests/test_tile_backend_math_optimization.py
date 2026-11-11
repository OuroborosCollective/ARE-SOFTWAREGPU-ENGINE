import unittest
from unittest import mock
import numpy as np
import math
from software_gpu.graphics.tile_backend import rasterize_tiles
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Shader, Vertex

class TestTileBackendMathOptimization(unittest.TestCase):
    @mock.patch('numpy.floor')
    @mock.patch('numpy.ceil')
    def test_rasterize_tiles_uses_math_instead_of_numpy(self, mock_ceil, mock_floor):
        fb = Framebuffer(100, 100)

        class DummyShader(Shader):
            def vertex_shader(self, vertex):
                return vertex.position, {}
            def fragment_shader(self, varyings):
                return (1.0, 1.0, 1.0, 1.0)

        shader = DummyShader()

        s0 = np.array([10.0, 10.0, 0.5, 1.0])
        s1 = np.array([50.0, 10.0, 0.5, 1.0])
        s2 = np.array([30.0, 50.0, 0.5, 1.0])

        triangle = (s0, s1, s2, 1.0, 1.0, 1.0, {}, {}, {}, 800.0)

        from concurrent.futures import ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=1)

        rasterize_tiles(fb, [triangle], shader, tile_size=16, executor=executor, workers=1, compiled=False, planned=False, plan_policy=None, prepared_bins=None)

        mock_floor.assert_not_called()
        mock_ceil.assert_not_called()

if __name__ == '__main__':
    unittest.main()
