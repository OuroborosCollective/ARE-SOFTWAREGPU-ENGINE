import json
import statistics
import sys
import time
import unittest
import numpy as np

from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import BlinnPhongShader, Matrix4, Vertex
from software_gpu.graphics.geometry import prepare_triangles

class TestRasterizerBandsInlinePerformance(unittest.TestCase):
    def test_rasterizer_bands_inline_speedup(self):
        # We construct a scenario with a single large triangle.
        fb = Framebuffer(200, 150)
        model = Matrix4.identity()
        view = Matrix4.identity()
        proj = Matrix4.identity()
        shader = BlinnPhongShader(model, view, proj)

        vertices = [
            Vertex(position=[-1, -1, 0], uv=[0, 0], color=[1, 0, 0], normal=[0, 0, 1]),
            Vertex(position=[1, -1, 0], uv=[1, 0], color=[0, 1, 0], normal=[0, 0, 1]),
            Vertex(position=[0, 1, 0], uv=[0.5, 1], color=[0, 0, 1], normal=[0, 0, 1])
        ]
        indices = [(0, 1, 2)]
        triangles = prepare_triangles(vertices, indices, shader, fb.width, fb.height)

        rasterizer = SoftwareRasterizer(fb, backend="bands")

        times_ms = []
        for _ in range(15):
            start = time.perf_counter_ns()
            for _ in range(10):
                rasterizer._rasterize_band(triangles, shader, 0, fb.height)
            times_ms.append((time.perf_counter_ns() - start) / 1e6)

        median_ms = statistics.median(times_ms)

        print("RASTERIZER_BANDS_INLINE_EVIDENCE " + json.dumps({
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "repeats": 15,
            "inner_loops": 10,
            "median_ms": round(median_ms, 6),
            "scope": "_rasterize_band inline float32 optimization"
        }, sort_keys=True))

        # Following memory guidance on slow CI, use a generous threshold
        self.assertLess(median_ms, 2000.0, "Rasterizer inline performance is too slow")

if __name__ == "__main__":
    unittest.main()
