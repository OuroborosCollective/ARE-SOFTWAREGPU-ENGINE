"""Raster correctness contract: perspective interpolation, depth tie-breaks,
numeric fail-closed behavior, index errors and the alpha non-goal.

Every test drives the real Framebuffer/SoftwareRasterizer paths on both CPU
backends (bands reference and tiles) with analytic expectations, not mocks.
"""
import unittest

import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex


class FlatColorShader:
    """Pass-through clip position + per-vertex color varying."""

    def vertex_shader(self, vertex):
        return (np.asarray(vertex.position, dtype=np.float64),
                {"color": np.asarray(vertex.color, dtype=np.float64)})

    def fragment_shader(self, varyings):
        rgb = np.clip(np.asarray(varyings["color"]) * 255.0, 0, 255)
        return int(rgb[0]), int(rgb[1]), int(rgb[2]), 255


class AlphaShader(FlatColorShader):
    """Adds a flat scalar alpha varying to pin the current alpha contract."""

    def vertex_shader(self, vertex):
        position, varyings = super().vertex_shader(vertex)
        varyings["alpha"] = int(vertex.uv[0])
        return position, varyings

    def fragment_shader(self, varyings):
        r, g, b, _ = super().fragment_shader(varyings)
        return r, g, b, int(varyings["alpha"])


def clip_quad(z0=0.5, z1=0.5):
    """Receding unit quad: near edge w=1 at NDC y=-0.5, far edge w=4 at
    NDC y=+0.5. Color ramps 0 -> 1 from near to far."""
    near_l = (-0.8, -0.5, z0, 1.0)
    near_r = (0.8, -0.5, z0, 1.0)
    far_l = (-0.8 * 4, 0.5 * 4, z1 * 4, 4.0)
    far_r = (0.8 * 4, 0.5 * 4, z1 * 4, 4.0)
    verts = [
        Vertex(np.array(near_l, dtype=np.float64), color=np.array([0., 0., 0.])),
        Vertex(np.array(near_r, dtype=np.float64), color=np.array([0., 0., 0.])),
        Vertex(np.array(far_l, dtype=np.float64), color=np.array([1., 1., 1.])),
        Vertex(np.array(far_r, dtype=np.float64), color=np.array([1., 1., 1.])),
    ]
    return verts, [(0, 1, 2), (1, 3, 2)]


def render(vertices, faces, shader=None, backend="tiles", size=128, threads=1):
    fb = Framebuffer(size, size)
    fb.clear(16, 25, 38, 255, depth=1.0)
    rasterizer = SoftwareRasterizer(fb, backend=backend, num_threads=threads,
                                    tile_size=16)
    try:
        rasterizer.draw_mesh(vertices, faces, shader or FlatColorShader())
    finally:
        rasterizer.executor.shutdown(wait=True)
    return fb


def flat_tri(ndc_points, color, alpha=255):
    verts = [Vertex(np.array([x, y, z, 1.0]), color=np.asarray(color, float),
                    uv=np.array([alpha, 0.0])) for x, y, z in ndc_points]
    return verts, [(0, 1, 2)]


class TestPerspectiveInterpolation(unittest.TestCase):
    def test_receding_quad_matches_perspective_not_affine(self):
        """Slanted-surface ramp: at screen center the perspective-correct value
        is t=(y+0.5)/(2.5-3y) ~ 0.205, affine would give 0.5."""
        for backend in ("bands", "tiles"):
            with self.subTest(backend=backend):
                verts, faces = clip_quad()
                fb = render(verts, faces, backend=backend)
                row = 63
                ndc_y = 1.0 - 2.0 * (row + 0.5) / 128
                expected = (ndc_y + 0.5) / (2.5 - 3.0 * ndc_y)
                cols = slice(48, 80)
                # coverage via depth, not color: the background red is 16
                self.assertTrue((fb.depth_buffer[row, cols] < 1.0).all())
                measured = fb.color_buffer[row, cols, 0].astype(float).mean() / 255.0
                self.assertAlmostEqual(measured, expected, delta=0.03)
                self.assertGreater(abs(measured - 0.5), 0.10)

    def test_both_backends_byte_identical_on_receding_quad(self):
        verts, faces = clip_quad()
        bands = render(verts, faces, backend="bands")
        tiles = render(verts, faces, backend="tiles")
        self.assertTrue(np.array_equal(bands.color_buffer, tiles.color_buffer))
        self.assertTrue(np.array_equal(bands.depth_buffer, tiles.depth_buffer))


class TestDepthContract(unittest.TestCase):
    QUAD_A = [(-0.6, -0.6, 0.4), (0.6, -0.6, 0.4), (0.0, 0.6, 0.4)]   # near red
    QUAD_B = [(-0.5, -0.5, 0.6), (0.5, -0.5, 0.6), (0.0, 0.5, 0.6)]   # far blue

    def _overlap_pixel(self, fb):
        return tuple(int(v) for v in fb.color_buffer[64, 64])

    def test_nearer_triangle_wins_regardless_of_submission_order(self):
        for backend in ("bands", "tiles"):
            with self.subTest(backend=backend):
                v1, f1 = flat_tri(self.QUAD_A, [1, 0, 0])
                v2, f2 = flat_tri(self.QUAD_B, [0, 0, 1])
                fb1 = render(v1 + v2, f1 + [(a + 3, b + 3, c + 3) for a, b, c in f2],
                             backend=backend)
                fb2 = render(v2 + v1, f2 + [(a + 3, b + 3, c + 3) for a, b, c in f1],
                             backend=backend)
                self.assertEqual(self._overlap_pixel(fb1)[:3], (255, 0, 0))
                self.assertEqual(self._overlap_pixel(fb2)[:3], (255, 0, 0))

    def test_equal_depth_keeps_first_submission(self):
        """Strict '<' depth compare: later equal-depth fragments never replace."""
        near_green = [(-0.6, -0.6, 0.5), (0.6, -0.6, 0.5), (0.0, 0.6, 0.5)]
        near_blue = [(-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.0, 0.5, 0.5)]
        v1, f1 = flat_tri(near_green, [0, 1, 0])
        v2, f2 = flat_tri(near_blue, [0, 0, 1])
        fb = render(v1 + v2, f1 + [(a + 3, b + 3, c + 3) for a, b, c in f2])
        self.assertEqual(tuple(int(v) for v in fb.color_buffer[64, 64, :3]),
                         (0, 255, 0))


class TestNumericFailClosed(unittest.TestCase):
    GOOD = [(-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.0, 0.5, 0.5)]

    def _assert_untouched(self, fb):
        self.assertTrue((fb.depth_buffer == 1.0).all())

    def test_nan_vertex_discards_only_that_primitive(self):
        bad = [Vertex(np.array([np.nan, 0.0, 0.5, 1.0]), color=np.array([1., 0., 0.])),
               Vertex(np.array([0.5, -0.5, 0.5, 1.0]), color=np.array([1., 0., 0.])),
               Vertex(np.array([0.0, 0.5, 0.5, 1.0]), color=np.array([1., 0., 0.]))]
        good, gf = flat_tri(self.GOOD, [0, 1, 0])
        fb = render(bad + good, [(0, 1, 2)] + [(a + 3, b + 3, c + 3) for a, b, c in gf])
        self.assertEqual(tuple(int(v) for v in fb.color_buffer[64, 64, :3]),
                         (0, 255, 0))  # good triangle unaffected

    def test_inf_varying_discards_primitive(self):
        verts = [Vertex(np.array([x, y, z, 1.0]), color=np.array([np.inf, 0., 0.]))
                 for x, y, z in self.GOOD]
        fb = render(verts, [(0, 1, 2)])
        self._assert_untouched(fb)

    def test_extreme_coordinates_clip_without_crash(self):
        huge = [(-1e9, -1e9, 0.5), (1e9, -1e9, 0.5), (0.0, 1e9, 0.5)]
        verts = [Vertex(np.array([x, y, z, 1.0]), color=np.array([1., 1., 1.]))
                 for x, y, z in huge]
        fb = render(verts, [(0, 1, 2)])
        self.assertTrue(np.isfinite(fb.depth_buffer).all())
        self.assertTrue(np.isfinite(fb.color_buffer.astype(float)).all())

    def test_invalid_indices_raise_programming_error(self):
        verts, _ = flat_tri(self.GOOD, [1, 0, 0])
        for face in ((0, 1, 99), (0, 1, -1), (0, 1)):
            with self.subTest(face=face):
                with self.assertRaises((IndexError, ValueError)):
                    render(verts, [face])


class TestAlphaNonGoal(unittest.TestCase):
    def test_alpha_is_stored_verbatim_and_ignored_for_composition(self):
        """Pins the documented non-goal: no alpha blending exists. A 'fully
        transparent' red triangle still owns depth and blocks a later opaque
        blue one; its alpha byte is stored unchanged."""
        red = [(-0.6, -0.6, 0.4), (0.6, -0.6, 0.4), (0.0, 0.6, 0.4)]
        blue = [(-0.5, -0.5, 0.6), (0.5, -0.5, 0.6), (0.0, 0.5, 0.6)]
        v1, f1 = flat_tri(red, [1, 0, 0], alpha=0)
        v2, f2 = flat_tri(blue, [0, 0, 1], alpha=255)
        fb = render(v1 + v2, f1 + [(a + 3, b + 3, c + 3) for a, b, c in f2],
                    shader=AlphaShader())
        self.assertEqual(tuple(int(v) for v in fb.color_buffer[64, 64]),
                         (255, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
