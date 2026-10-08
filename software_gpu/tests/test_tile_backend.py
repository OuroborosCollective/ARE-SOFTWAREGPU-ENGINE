"""Real CPU raster regressions against the historical band reference."""
import unittest

import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Shader, Vertex
from software_gpu.graphics.postprocess import MSAAFramebuffer


class ColorShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {"color": vertex.color}

    def fragment_shader(self, varyings):
        rgba = np.clip(np.asarray(varyings["color"]) * 255, 0, 255).astype(np.uint8)
        return int(rgba[0]), int(rgba[1]), int(rgba[2]), 255


def verts(points, color):
    return [Vertex(np.array(p, dtype=np.float32), color=np.array(color, dtype=np.float32)) for p in points]


class TestTileRasterizer(unittest.TestCase):
    def setUp(self):
        self.sh = ColorShader()
        # Real rendering: overlapping triangles, shared edges, partially
        # offscreen geometry and depth ties. No mock or stub render functions.
        self.scenes = [
            (verts([(-0.92, -0.86, .32), (.90, -.84, .32), (.0, .94, .32)], (.8, .12, .17)), [(0, 1, 2)]),
            (verts([(-.81, .82, .12), (.86, .81, .12), (.1, -.72, .12)], (.3, .9, .2)), [(0, 1, 2)]),
            (verts([(-1.25, -.20, .22), (.7, -.14, .22), (-.60, .34, .22)], (.1, .2, .88)), [(0, 1, 2)]),
            (verts([(-.38, -.34, .25), (.47, -.25, .25), (.10, .51, .25)], (.92, .1, .2)), [(0, 1, 2)]),
            (verts([(-.38, -.34, .25), (.47, -.25, .25), (.10, .51, .25)], (.2, .8, .7)), [(0, 1, 2)]),
        ]

    def _draw(self, backend, tile_size, workers):
        fb = Framebuffer(95, 79)
        fb.clear(20, 15, 10, 255, depth=1.0)
        rast = SoftwareRasterizer(fb, tile_size=tile_size, num_threads=workers, backend=backend)
        try:
            for vs, faces in self.scenes:
                rast.draw_mesh(vs, faces, self.sh)
        finally:
            rast.executor.shutdown(wait=True)
        return fb

    def test_tiled_matches_band_reference_for_overlap(self):
        original = self._draw("bands", 16, 1)
        self.assertGreater(np.count_nonzero(original.depth_buffer < 1.0), 30)
        for size in (8, 16, 32, 64):
            for workers in (1, 2, 4):
                with self.subTest(tile_size=size, workers=workers):
                    out = self._draw("tiles", size, workers)
                    np.testing.assert_array_equal(out.color_buffer, original.color_buffer)
                    np.testing.assert_allclose(out.depth_buffer, original.depth_buffer, atol=1e-7, rtol=1e-6)

    def test_repeatable_byte_identical_parallel(self):
        a = self._draw("tiles", 16, 4)
        b = self._draw("tiles", 16, 4)
        np.testing.assert_array_equal(a.color_buffer, b.color_buffer)
        np.testing.assert_array_equal(a.depth_buffer, b.depth_buffer)

    def test_tile_validation(self):
        for size in (-2, 0, 257):
            with self.subTest(size=size), self.assertRaises(ValueError):
                SoftwareRasterizer(Framebuffer(8, 8), tile_size=size)
        with self.assertRaises(ValueError):
            SoftwareRasterizer(Framebuffer(8, 8), num_threads=0)
        with self.assertRaises(ValueError):
            SoftwareRasterizer(Framebuffer(8, 8), backend="magic-gpu")

    def test_msaa_uint16_resolve_matches_float_reference(self):
        fb = MSAAFramebuffer(61, 17, samples=4)
        rng = np.random.default_rng(106)
        fb.color_samples[...] = rng.integers(0, 256, size=fb.color_samples.shape, dtype=np.uint8)
        fb.depth_samples[...] = rng.uniform(0, 1, size=fb.depth_samples.shape).astype(np.float32)
        old_float_resolve = np.mean(fb.color_samples.astype(np.float32), axis=2).astype(np.uint8)
        new_resolve = fb.resolve()
        np.testing.assert_array_equal(new_resolve.color_buffer, old_float_resolve)
        np.testing.assert_array_equal(new_resolve.depth_buffer, fb.depth_samples.min(axis=2))
        with self.assertRaises(ValueError):
            MSAAFramebuffer(8, 8, samples=2)


if __name__ == "__main__":
    unittest.main()
