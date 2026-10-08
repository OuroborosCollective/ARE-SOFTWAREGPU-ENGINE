"""Differential tests for opt-in Numba/LLVM CPU rasterization.

These tests execute the real renderer and real Numba-compiled coverage kernel.
No GPU, mocks or artificial outputs are involved.
"""
from importlib.util import find_spec
import unittest

import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Shader, Vertex


class GradientShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {"color": vertex.color}

    def fragment_shader(self, varyings):
        rgb = np.clip(varyings["color"] * 255, 0, 255).astype(np.uint8)
        return int(rgb[0]), int(rgb[1]), int(rgb[2]), 255


@unittest.skipUnless(find_spec("numba") is not None, "optional jit extra not installed")
class TestLLVMCompiledTiles(unittest.TestCase):
    def _render(self, backend, workers):
        fb = Framebuffer(95, 79)
        fb.clear(11, 22, 33, 255, 1.0)
        engine = SoftwareRasterizer(fb, tile_size=16, num_threads=workers, backend=backend)
        shader = GradientShader()
        coords = [
            ((-.8, -.7, .22), (.0, .8, .22), (.87, -.7, .22)),
            ((-.85, -.1, .41), (.3, .92, .41), (.91, -.6, .41)),
            ((-.4, -.5, .15), (.06, .76, .15), (.55, -.51, .15)),
        ]
        try:
            for i, points in enumerate(coords):
                colors = (
                    (.15, .8, .3), (.91, .2, .4), (.36, .71, .95)
                )
                verts = [
                    Vertex(np.array(point, dtype=np.float32),
                           color=np.array(colors[(i+j) % len(colors)], dtype=np.float32))
                    for j, point in enumerate(points)
                ]
                engine.draw_mesh(verts, [(0, 1, 2)], shader)
        finally:
            engine.executor.shutdown(wait=True)
        return fb

    def test_compiled_cpu_matches_numpy_coverage(self):
        from software_gpu.graphics.compiled_tile import get_compiled_coverage
        reference = self._render("tiles", 1)
        compiled = self._render("tiles-jit", 1)
        np.testing.assert_array_equal(compiled.color_buffer, reference.color_buffer)
        np.testing.assert_allclose(compiled.depth_buffer, reference.depth_buffer, rtol=1e-6, atol=1e-7)
        self.assertTrue(get_compiled_coverage().signatures, "LLVM kernel was not compiled")

    def test_compiled_cpu_multiworker_repeatable(self):
        single = self._render("tiles-jit", 1)
        multiple = self._render("tiles-jit", 4)
        repeat = self._render("tiles-jit", 4)
        np.testing.assert_array_equal(single.color_buffer, multiple.color_buffer)
        np.testing.assert_array_equal(multiple.color_buffer, repeat.color_buffer)
        np.testing.assert_array_equal(multiple.depth_buffer, repeat.depth_buffer)


if __name__ == "__main__":
    unittest.main()
