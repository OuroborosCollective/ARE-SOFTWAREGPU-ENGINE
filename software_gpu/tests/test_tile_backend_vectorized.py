"""Slice B: pin the vectorized-varying tile backend against the bands reference.

The tile backend interpolates array varyings with a vectorized pre-pass
(inverse-W weighting, perspective factor) instead of per-pixel Python scalar
math. These tests prove the optimization is behavior-preserving: byte-identical
color/depth against the historical bands renderer across scene shapes, multiple
array/scalar varyings and all supported tile sizes.
"""
import unittest

import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex
from software_gpu.integrations.aurion.offline_render_worker import (
    _camera_transform,
    _orient_double_sided,
    build_procedural_mesh,
)

CAMERA = {"yaw_degrees": 25.0, "pitch_degrees": 20.0, "center_y": 0.0,
          "x_half_extent": 1.6, "y_half_extent": 1.6}


class MultiVaryingShader:
    """Two array varyings (color ramp + uv) and one scalar varying."""

    def vertex_shader(self, vertex):
        position = np.asarray(vertex.position, dtype=np.float64)
        return position, {
            "color": np.asarray(vertex.color, dtype=np.float64),
            "uv": np.asarray(vertex.uv, dtype=np.float64),
            "material": 7,
        }

    def fragment_shader(self, varyings):
        rgb = np.clip(varyings["color"] * 255.0 + varyings["uv"][0], 0, 255)
        return int(rgb[0]), int(rgb[1]), int(rgb[2]), 255


def sphere_scene(pixels, rings=10, segments=20, zoom=1.6, seed=686):
    verts, faces = build_procedural_mesh(seed=seed, rings=rings, segments=segments)
    camera = dict(CAMERA, x_half_extent=zoom, y_half_extent=zoom)
    clip = _camera_transform(verts, camera)
    faces = _orient_double_sided(clip, faces)
    mesh = []
    for i, v in enumerate(clip):
        shade = (i % 17) / 17.0
        mesh.append(Vertex(v, color=np.array([shade, 1.0 - shade, 0.5 * shade]),
                           uv=np.array([shade * 13.0, shade * 7.0])))
    return mesh, [tuple(int(i) for i in f) for f in faces]


def quad_scene(pixels):
    pts = [(-0.95, -0.95, 0.5), (0.95, -0.95, 0.5),
           (0.95, 0.95, 0.5), (-0.95, 0.95, 0.5)]
    mesh = [Vertex(np.array([x, y, z, 1.0]),
                   color=np.array([0.2 + i * 0.2, 0.9 - i * 0.2, 0.4]),
                   uv=np.array([float(i), float(3 - i)]))
            for i, (x, y, z) in enumerate(pts)]
    return mesh, [(0, 1, 2), (0, 2, 3)]


def render(mesh, faces, backend, pixels=96, tile_size=32):
    fb = Framebuffer(pixels, pixels)
    fb.clear(16, 25, 38, 255, depth=1.0)
    rasterizer = SoftwareRasterizer(fb, backend=backend, num_threads=1,
                                    tile_size=tile_size)
    try:
        rasterizer.draw_mesh(mesh, faces, MultiVaryingShader())
    finally:
        rasterizer.executor.shutdown(wait=True)
    return fb


def buffers_identical(a, b):
    return (np.array_equal(a.color_buffer, b.color_buffer)
            and np.array_equal(a.depth_buffer, b.depth_buffer))


class TestVectorizedVaryingsByteIdentity(unittest.TestCase):
    def test_sphere_scene_tiles_match_bands(self):
        mesh, faces = sphere_scene(96)
        self.assertTrue(buffers_identical(render(mesh, faces, "bands"),
                                          render(mesh, faces, "tiles")))

    def test_zoomed_big_triangle_scene_tiles_match_bands(self):
        mesh, faces = sphere_scene(96, zoom=0.25)
        self.assertTrue(buffers_identical(render(mesh, faces, "bands"),
                                          render(mesh, faces, "tiles")))

    def test_huge_quad_scene_tiles_match_bands(self):
        mesh, faces = quad_scene(96)
        self.assertTrue(buffers_identical(render(mesh, faces, "bands"),
                                          render(mesh, faces, "tiles")))

    def test_tile_size_does_not_change_output(self):
        """Tile size is a pure performance knob: 8/16/32/64 must agree."""
        mesh, faces = sphere_scene(96)
        reference = render(mesh, faces, "tiles", tile_size=32)
        for tile_size in (8, 16, 64):
            with self.subTest(tile_size=tile_size):
                self.assertTrue(
                    buffers_identical(reference,
                                      render(mesh, faces, "tiles",
                                             tile_size=tile_size)))

    def test_repeated_renders_are_deterministic(self):
        mesh, faces = sphere_scene(96)
        first = render(mesh, faces, "tiles")
        second = render(mesh, faces, "tiles")
        self.assertTrue(buffers_identical(first, second))


if __name__ == "__main__":
    unittest.main()
