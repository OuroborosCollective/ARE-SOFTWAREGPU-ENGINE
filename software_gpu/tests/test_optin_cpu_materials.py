"""Issue #285: real geometry/tiles, analytic RGB/depth and fail-closed profiles."""
import hashlib
import math
import unittest

import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.render_profiles import (
    FragmentPolicy, OptInCpuRenderer, ShadowMap, ShadowedShader,
    _decode, _encode, frame_receipt, resolve_4x,
)
from software_gpu.graphics.shader import Vertex


TRI = ((-0.8, -0.8, 0.4), (0.8, -0.8, 0.4), (0.0, 0.8, 0.4))


class Solid:
    def __init__(self, rgba, matrix=None):
        self.rgba = tuple(rgba)
        self.matrix = np.eye(4) if matrix is None else np.asarray(matrix)

    def vertex_shader(self, vertex):
        return self.matrix @ vertex.position, {}

    def fragment_shader(self, varying):
        return self.rgba


def triangle(z=0.4):
    return [Vertex(np.array((x, y, z, 1.0))) for x, y, _ in TRI]


def frame():
    fb = Framebuffer(64, 64)
    fb.clear(0, 0, 0, 255, depth=1.0)
    return fb


def pixel(fb):
    return tuple(int(x) for x in fb.color_buffer[32, 32])


class MaterialTests(unittest.TestCase):
    def test_default_opaque_unchanged_including_alpha_zero_and_first_owner(self):
        verts = triangle()
        ordinary = frame()
        optin = frame()
        r = SoftwareRasterizer(ordinary, backend="tiles", tile_size=16, num_threads=1)
        try:
            r.draw_mesh(verts, [(0, 1, 2)], Solid((255, 0, 0, 0)))
        finally:
            r.executor.shutdown(wait=True)
        with OptInCpuRenderer(optin) as o:
            o.draw_opaque(verts, [(0, 1, 2)], Solid((255, 0, 0, 0)))
            o.draw_opaque(verts, [(0, 1, 2)], Solid((0, 255, 0, 255)))
        self.assertEqual(ordinary.color_buffer.tobytes(), optin.color_buffer.tobytes())
        self.assertEqual(ordinary.depth_buffer.tobytes(), optin.depth_buffer.tobytes())
        self.assertEqual(pixel(optin), (255, 0, 0, 0))
        self.assertAlmostEqual(float(optin.depth_buffer[32, 32]), 0.4, places=6)

    def test_alpha_test_0_255_and_cutoff_and_depth(self):
        verts = triangle()
        for alpha, should_write in ((0, False), (127, False), (128, True), (255, True)):
            with self.subTest(alpha=alpha):
                fb = frame()
                with OptInCpuRenderer(fb) as r:
                    r.draw_alpha_test(verts, [(0, 1, 2)], Solid((255, 20, 50, alpha)))
                self.assertEqual(pixel(fb) == (255, 20, 50, alpha), should_write)
                self.assertEqual(bool(fb.depth_buffer[32, 32] < 1.0), should_write)

    def test_alpha_discard_preserves_later_depth_owner(self):
        fb = frame()
        with OptInCpuRenderer(fb) as r:
            r.draw_alpha_test(triangle(0.3), [(0, 1, 2)], Solid((255, 0, 0, 0)))
            r.draw_opaque(triangle(0.6), [(0, 1, 2)], Solid((0, 0, 255, 255)))
        self.assertEqual(pixel(fb), (0, 0, 255, 255))
        self.assertAlmostEqual(float(fb.depth_buffer[32, 32]), 0.6, places=6)

    def test_blend_linear_srgb_not_naive_and_no_depth_write(self):
        fb = frame()
        with OptInCpuRenderer(fb) as r:
            r.draw_opaque(triangle(0.7), [(0, 1, 2)], Solid((0, 0, 0, 255)))
            before = fb.depth_buffer.tobytes()
            r.blend_sorted([(0.4, triangle(0.4), [(0, 1, 2)], Solid((255, 255, 255, 128)))])
        self.assertEqual(pixel(fb), (188, 188, 188, 255))
        self.assertEqual(before, fb.depth_buffer.tobytes())
        self.assertNotEqual(pixel(fb)[:3], (128, 128, 128))

    def test_zero_alpha_and_opaque_depth_behind(self):
        fb = frame()
        with OptInCpuRenderer(fb) as r:
            r.draw_opaque(triangle(0.4), [(0, 1, 2)], Solid((10, 20, 30, 255)))
            before = (fb.color_buffer.tobytes(), fb.depth_buffer.tobytes())
            r.blend_sorted([(0.2, triangle(0.2), [(0, 1, 2)], Solid((255, 0, 0, 0))),
                            (0.8, triangle(0.8), [(0, 1, 2)], Solid((0, 255, 0, 255)))])
            self.assertEqual(before, (fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()))

    def test_sorted_overdraw_and_stable_ties(self):
        red = (255, 0, 0, 128)
        blue = (0, 0, 255, 128)
        near = (0.2, triangle(0.2), [(0, 1, 2)], Solid(red))
        far = (0.8, triangle(0.8), [(0, 1, 2)], Solid(blue))
        hashes = []
        for workers in (1, 3):
            fb = frame()
            with OptInCpuRenderer(fb, workers=workers) as r:
                r.blend_sorted([near, far])
            hashes.append((hashlib.sha256(fb.color_buffer.tobytes()).hexdigest(),
                           hashlib.sha256(fb.depth_buffer.tobytes()).hexdigest()))
            self.assertEqual(float(fb.depth_buffer[32, 32]), 1.0)
            self.assertGreater(pixel(fb)[0], 0)
            self.assertGreater(pixel(fb)[2], 0)
        self.assertEqual(hashes[0], hashes[1])
        tie1 = frame()
        tie2 = frame()
        with OptInCpuRenderer(tie1) as r:
            r.blend_sorted([(0.5, near[1], near[2], near[3]),
                            (0.5, far[1], far[2], far[3])])
        with OptInCpuRenderer(tie2) as r:
            r.blend_sorted([(0.5, far[1], far[2], far[3]),
                            (0.5, near[1], near[2], near[3])])
        self.assertNotEqual(pixel(tie1), pixel(tie2))

    def test_top_left_shared_edge_no_double_blend(self):
        verts = [Vertex(np.array((-0.8, -0.8, 0.4, 1.0))),
                 Vertex(np.array((0.8, -0.8, 0.4, 1.0))),
                 Vertex(np.array((-0.8, 0.8, 0.4, 1.0))),
                 Vertex(np.array((0.8, 0.8, 0.4, 1.0)))]
        fb = frame()
        with OptInCpuRenderer(fb) as r:
            r.blend_sorted([(0.4, verts, [(0, 1, 2), (1, 3, 2)],
                             Solid((255, 255, 255, 128)))])
        self.assertEqual(pixel(fb), (188, 188, 188, 255))

    def test_fail_closed_nan_rgba_and_transactional_pixels(self):
        fb = frame()
        before = fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()
        with OptInCpuRenderer(fb) as r:
            with self.assertRaisesRegex(ValueError, "RGBA8"):
                r.draw_opaque(triangle(), [(0, 1, 2)], Solid((float("nan"), 0, 0, 255)))
            with self.assertRaisesRegex(ValueError, "SORT_DEPTH"):
                r.blend_sorted([(math.nan, triangle(), [(0, 1, 2)], Solid((255, 0, 0, 255)))])
        self.assertEqual((fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()), before)
        with self.assertRaisesRegex(ValueError, "MATERIAL_MODE"):
            FragmentPolicy("transparent")
        with self.assertRaisesRegex(ValueError, "ALPHA_CUTOFF"):
            FragmentPolicy("alpha-test", -1)

    def test_shadow_map_occlusion_and_light_depth_readback(self):
        fb = frame()
        with OptInCpuRenderer(fb, workers=2) as r:
            shadow = r.make_shadow_map([(triangle(0.2), [(0, 1, 2)])],
                                       np.eye(4), resolution=64)
            r.draw_opaque(triangle(0.6), [(0, 1, 2)],
                          ShadowedShader(Solid((255, 100, 0, 255)), shadow,
                                         ambient=0.25, bias=0))
        self.assertAlmostEqual(float(shadow.depth[32, 32]), 0.2, places=6)
        self.assertFalse(shadow.visible((0, 0, 0.6), bias=0))
        self.assertTrue(shadow.visible((0, 0, 0.1), bias=0))
        self.assertEqual(pixel(fb), (_encode(_decode(255) * 0.25),
                                     _encode(_decode(100) * 0.25), 0, 255))
        with self.assertRaises(ValueError):
            shadow.depth[0, 0] = 0

    def test_shadow_invalid_projection_and_bias(self):
        shadow = ShadowMap(np.ones((2, 2), np.float32), np.eye(4))
        with self.assertRaisesRegex(ValueError, "SHADOW_BIAS"):
            shadow.visible((0, 0, 0), bias=math.nan)
        with self.assertRaisesRegex(ValueError, "SHADOW_WORLD"):
            shadow.visible((0, math.nan, 0))
        with self.assertRaisesRegex(ValueError, "SHADOW_DEPTH"):
            ShadowMap(np.array([[math.nan]], dtype=np.float32), np.eye(4))

    def test_four_sample_resolve_linear_alpha_weighted_and_depth(self):
        sample = Framebuffer(2, 2)
        sample.clear(0, 0, 0, 0, depth=1.0)
        sample.color_buffer[0, 0] = (255, 255, 255, 255)
        sample.depth_buffer[0, 0] = 0.2
        out = resolve_4x(sample)
        self.assertEqual(tuple(int(v) for v in out.color_buffer[0, 0]),
                         (255, 255, 255, 64))
        self.assertAlmostEqual(float(out.depth_buffer[0, 0]), 0.2, places=6)
        with self.assertRaisesRegex(ValueError, "4X_RESOLVE"):
            resolve_4x(Framebuffer(3, 2))

    def test_frame_receipt_fingerprint(self):
        fb = frame()
        receipt = frame_receipt(fb, "opaque", "triangle")
        self.assertEqual(receipt["rgba_sha256"],
                         hashlib.sha256(fb.color_buffer.tobytes()).hexdigest())
        self.assertEqual(receipt["depth_sha256"],
                         hashlib.sha256(fb.depth_buffer.tobytes()).hexdigest())
        self.assertEqual(receipt["no_gpu_or_fps_claim"], True)


if __name__ == "__main__":
    unittest.main()
