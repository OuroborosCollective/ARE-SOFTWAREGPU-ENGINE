"""Slice C: pin the vectorized triangle-setup fast path in prepare_triangles.

prepare_triangles gained a vectorized fast path for fully-inside faces
(AeroRaster/GLimpSW-style batch setup: plane tests, perspective divide,
screen mapping and area as whole-array ops). The clipped-face path is
unchanged. These tests pin exact behavioral equivalence against a verbatim
copy of the original per-face implementation as the oracle.
"""
import unittest

import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.geometry import (
    _MIN_W,
    clip_triangle,
    edge_function,
    prepare_triangles,
)
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex
from software_gpu.integrations.aurion.offline_render_worker import (
    _camera_transform,
    _FlatShader,
    _orient_double_sided,
    build_procedural_mesh,
)

CAMERA = {"yaw_degrees": 25.0, "pitch_degrees": 20.0, "center_y": 0.0,
          "x_half_extent": 1.6, "y_half_extent": 1.6}


def oracle_prepare_triangles(vertices, indices, shader, width: int, height: int):
    """Verbatim copy of the pre-Slice-C per-face implementation (test oracle)."""
    transformed = []
    for vertex in vertices:
        position, attrs = shader.vertex_shader(vertex)
        pos = np.asarray(position, dtype=np.float64)
        if pos.shape != (4,) or not np.isfinite(pos).all():
            transformed.append(None)
            continue
        if not isinstance(attrs, dict):
            raise TypeError("vertex shader varyings must be a dict")
        if any(
            isinstance(value, np.ndarray) and not np.isfinite(value).all()
            for value in attrs.values()
        ):
            transformed.append(None)
            continue
        transformed.append((pos, attrs))

    result = []
    for face in indices:
        if len(face) != 3 or any(
            not isinstance(i, (int, np.integer)) or i < 0 or i >= len(transformed)
            for i in face
        ):
            raise IndexError("triangle index outside vertex array")
        triangle = [transformed[i] for i in face]
        if any(point is None for point in triangle):
            continue
        for clipped in clip_triangle(triangle):
            screen = []
            inverse_w = []
            for position, _ in clipped:
                w = float(position[3])
                if w < _MIN_W:
                    break
                inv = 1.0 / w
                ndc = position[:3] * inv
                s = np.array([
                    (ndc[0] + 1.0) * 0.5 * width,
                    (1.0 - ndc[1]) * 0.5 * height,
                    ndc[2],
                ], dtype=np.float32)
                if not np.isfinite(s).all():
                    break
                screen.append(s)
                inverse_w.append(inv)
            if len(screen) != 3:
                continue
            area = float(edge_function(screen[0], screen[1], screen[2]))
            if not np.isfinite(area) or area <= 1e-9:
                continue
            result.append((
                screen[0], screen[1], screen[2],
                inverse_w[0], inverse_w[1], inverse_w[2],
                clipped[0][1], clipped[1][1], clipped[2][1], area,
            ))
    return result


def tri_lists_equal(a, b):
    """Value equality of emitted triangle tuples (attrs by content)."""
    if len(a) != len(b):
        return False
    for ta, tb in zip(a, b):
        for xa, xb in zip(ta[:3], tb[:3]):
            if not isinstance(xb, np.ndarray) or not np.array_equal(xa, xb):
                return False
        if ta[3:6] != tb[3:6] or ta[9] != tb[9]:
            return False
        for k in (6, 7, 8):
            da, db = ta[k], tb[k]
            if da.keys() != db.keys():
                return False
            for key in da:
                va, vb = da[key], db[key]
                if isinstance(va, np.ndarray):
                    if not np.array_equal(va, vb):
                        return False
                elif va != vb:
                    return False
    return True


def sphere_mesh(seed=686, rings=8, segments=16, zoom=1.6):
    verts, faces = build_procedural_mesh(seed=seed, rings=rings, segments=segments)
    camera = dict(CAMERA, x_half_extent=zoom, y_half_extent=zoom)
    clip = _camera_transform(verts, camera)
    faces = _orient_double_sided(clip, faces)
    mesh = [Vertex(v, color=np.array([0.8, 0.7, 0.45])) for v in clip]
    return mesh, [tuple(int(i) for i in f) for f in faces]


class TestSetupFastPathEquivalence(unittest.TestCase):
    def test_matches_oracle_across_seeds_zooms_and_aspect(self):
        for seed in range(12):
            for zoom in (1.6, 0.9, 0.25, 0.12):  # 0.25/0.12 force real clipping
                mesh, faces = sphere_mesh(seed=seed, zoom=zoom)
                for size in ((128, 128), (96, 64)):
                    with self.subTest(seed=seed, zoom=zoom, size=size):
                        expected = oracle_prepare_triangles(mesh, faces,
                                                            _FlatShader(), *size)
                        actual = prepare_triangles(mesh, faces,
                                                   _FlatShader(), *size)
                        self.assertTrue(tri_lists_equal(expected, actual))

    def test_attrs_dicts_are_shared_per_vertex_within_a_call(self):
        """Faces referencing the same vertex must get the identical attrs
        object (the clipping slow path preserves object references)."""
        mesh, faces = sphere_mesh(seed=3)
        tris = prepare_triangles(mesh, faces, _FlatShader(), 128, 128)
        by_vertex = {}
        for tri, face in zip(tris, faces):
            for slot, vi in enumerate(face):
                attrs = tri[6 + slot]
                if vi in by_vertex:
                    self.assertIs(by_vertex[vi], attrs)
                else:
                    by_vertex[vi] = attrs

    def test_empty_and_invalid_faces_behave_like_the_oracle(self):
        mesh, _ = sphere_mesh(seed=1)
        self.assertEqual(prepare_triangles(mesh, [], _FlatShader(), 128, 128), [])
        small = mesh[:3]
        for bad in ([(0, 1, 99)], [(0, 1, -1)], [(0, 1)], [(0, 1, 2.5)]):
            with self.subTest(face=bad):
                with self.assertRaises((IndexError, ValueError)):
                    prepare_triangles(small, bad, _FlatShader(), 128, 128)

    def test_nonfinite_vertices_discard_parity(self):
        mesh, faces = sphere_mesh(seed=2)
        mesh = list(mesh)
        mesh[5] = Vertex(np.array([np.nan, 0.0, 0.5, 1.0]),
                         color=np.array([1.0, 0.0, 0.0]))
        expected = oracle_prepare_triangles(mesh, faces, _FlatShader(), 128, 128)
        actual = prepare_triangles(mesh, faces, _FlatShader(), 128, 128)
        self.assertTrue(tri_lists_equal(expected, actual))
        self.assertLess(len(actual), len(faces))  # discards really happened

    def test_render_output_byte_identical_both_backends(self):
        """End-to-end: bands and tiles digests equal oracle-driven output."""
        mesh, faces = sphere_mesh(seed=99, rings=16, segments=40)
        for backend in ("bands", "tiles"):
            with self.subTest(backend=backend):
                digests = []
                for prep in (oracle_prepare_triangles, prepare_triangles):
                    fb = Framebuffer(96, 96)
                    fb.clear(16, 25, 38, 255, depth=1.0)
                    rasterizer = SoftwareRasterizer(fb, backend=backend,
                                                    num_threads=1, tile_size=32)
                    try:
                        triangles = prep(mesh, faces, _FlatShader(), 96, 96)
                        # draw via the real backend entry points
                        if backend == "bands":
                            rasterizer._rasterize_band(triangles, _FlatShader(),
                                                       0, 96)
                        else:
                            from software_gpu.graphics.tile_backend import (
                                rasterize_tiles,
                            )
                            rasterize_tiles(fb, triangles, _FlatShader(), 32,
                                            rasterizer.executor, 1)
                    finally:
                        rasterizer.executor.shutdown(wait=True)
                    import hashlib
                    digests.append(hashlib.sha256(
                        fb.color_buffer.tobytes()
                        + fb.depth_buffer.tobytes()).hexdigest())
                self.assertEqual(digests[0], digests[1])


if __name__ == "__main__":
    unittest.main()
