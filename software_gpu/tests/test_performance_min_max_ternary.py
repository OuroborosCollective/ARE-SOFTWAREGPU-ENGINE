import unittest
import time
import math
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Shader
from software_gpu.graphics.geometry import is_top_left

class DummyShader(Shader):
    def vertex_shader(self, vertex, uniforms):
        return vertex.position[:4], {"color": (1, 1, 1, 1)}

    def fragment_shader(self, varyings):
        return 1.0, 1.0, 1.0, 1.0

class TestPerformanceMinMaxTernary(unittest.TestCase):
    def test_performance_optimization(self):
        # We test that rasterizing many small triangles runs fast enough.
        # This confirms that our optimization replacing min/max with inline ternary logic
        # is actually efficient.
        fb = Framebuffer(64, 64)
        rasterizer = SoftwareRasterizer(fb, backend="bands", num_threads=1)
        shader = DummyShader()

        # Create a bunch of tiny triangles
        triangles = []
        for i in range(100):
            for j in range(100):
                x = (i / 100.0) * 64.0
                y = (j / 100.0) * 64.0

                # Format: (s0, s1, s2, inv_w0, inv_w1, inv_w2, v0_var, v1_var, v2_var, area)
                s0 = (x, y, 0.5)
                s1 = (x + 1.0, y, 0.5)
                s2 = (x, y + 1.0, 0.5)

                triangles.append((
                    s0, s1, s2,
                    1.0, 1.0, 1.0,
                    {}, {}, {},
                    0.5
                ))

        start_time = time.perf_counter()
        rasterizer._rasterize_band(triangles, shader, 0, 64)
        elapsed_time = time.perf_counter() - start_time

        # Expect very fast execution, generous 5.0s threshold to prevent flakiness
        self.assertLess(elapsed_time, 5.0, f"Rasterization took too long: {elapsed_time}s")
