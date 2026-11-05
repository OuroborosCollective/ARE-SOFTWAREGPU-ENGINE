import unittest
import time
from software_gpu.core.device import VirtualGPU
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Shader
import numpy as np

class DummyShader(Shader):
    def vertex_shader(self, vertex):
        return np.array([vertex[0], vertex[1], vertex[2], 1.0]), {}
    def fragment_shader(self, varyings):
        return 255, 0, 0, 255

class TestAABBPerformance(unittest.TestCase):
    def test_aabb_performance(self):
        fb = Framebuffer(800, 600)
        vertices = []
        indices = []
        for i in range(100):
            for j in range(100):
                x = i * 8
                y = j * 6
                idx = len(vertices)
                vertices.append([x, y, 1.0])
                vertices.append([x+5, y, 1.0])
                vertices.append([x, y+4, 1.0])
                indices.append((idx, idx+1, idx+2))

        rasterizer = SoftwareRasterizer(fb, backend="bands")
        start = time.perf_counter()
        rasterizer.draw_mesh(vertices, indices, DummyShader())
        end = time.perf_counter()

        duration = end - start
        self.assertLess(duration, 15.0, "AABB calculation is too slow")

if __name__ == '__main__':
    unittest.main()
