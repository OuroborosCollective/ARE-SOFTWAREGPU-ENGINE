"""Differential contracts for the opt-in per-draw deferred-visibility research lane.

These are actual framebuffer/depth tests. They do not assert a speedup.
"""
import unittest
import numpy as np

from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Shader, Vertex


def stack_mesh():
    """Five fully overlapping squares with depth ties, occlusion and colors."""
    vertices, faces = [], []
    points = ((-.92, -.88), (.91, -.88), (.91, .86), (-.92, .86))
    for n, z in enumerate((.8, .35, .6, .2, .4)):
        base = len(vertices)
        for i, (x, y) in enumerate(points):
            vertices.append(Vertex(np.array([x, y, z, 1], dtype=np.float32),
                                   color=np.array([.11 + n*.13, .15 + i*.17, .47 - n*.07])))
        faces.extend(((base, base+1, base+2), (base, base+2, base+3)))
    return vertices, faces


def rendered(mesh, faces, backend, workers=1, size=72, tile_size=16, clear_depth=1.0):
    fb = Framebuffer(size, size)
    fb.clear(19, 31, 43, 201, depth=clear_depth)
    renderer = SoftwareRasterizer(fb, backend=backend, tile_size=tile_size,
                                  num_threads=workers)
    try:
        renderer.draw_mesh(mesh, faces, VertexColorShader())
        return fb.color_buffer.tobytes(), fb.depth_buffer.tobytes(), renderer.last_deferred_receipt
    finally:
        renderer.executor.shutdown(wait=True)


class StatefulShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {"color": vertex.color}

    def fragment_shader(self, varyings):
        self.calls = getattr(self, "calls", 0) + 1
        return self.calls & 255, 0, 0, 255


class TestDeferredVisibility(unittest.TestCase):
    def test_real_overdraw_matches_tiles_and_skips_overwritten_fragments(self):
        mesh, faces = stack_mesh()
        reference, depth, _ = rendered(mesh, faces, "tiles")
        for workers in (1, 2, 4):
            for tile in (8, 16, 32):
                with self.subTest(workers=workers, tile=tile):
                    color, z, receipt = rendered(
                        mesh, faces, "tiles-deferred", workers=workers, tile_size=tile
                    )
                    self.assertEqual(reference, color)
                    self.assertEqual(depth, z)
                    self.assertEqual(receipt["protocol"], "are.deferred-visibility.v1")
                    self.assertGreater(receipt["candidate_depth_passes"],
                                       receipt["final_shaded_samples"])
                    self.assertEqual(receipt["avoided_fragment_invocations"],
                                     receipt["candidate_depth_passes"] -
                                     receipt["final_shaded_samples"])
                    self.assertGreater(receipt["final_shaded_samples"], 0)

    def test_perspective_clip_top_left_ties_and_preexisting_depth(self):
        cases = [
            ([Vertex(np.array(p, dtype=np.float32),
                     color=np.array([i/3, .27, 1-i/3], dtype=np.float32))
              for i, p in enumerate(((-.8,-.8,.2,1),(.8,-.8,.2,1),(.8,.8,.2,1),(-.8,.8,.2,1)))],
             [(0,1,2),(0,2,3),(0,1,2)]),
            ([Vertex(np.array(p, dtype=np.float32),
                     color=np.array([.2,.7,.4], dtype=np.float32))
              for p in ((-.9,-.7,-2.,1),(.9,-.7,.1,1),(.1,.9,.3,1))],
             [(0,1,2)]),
            stack_mesh(),
        ]
        for mesh, faces in cases:
            for depth_init in (.4, 1.0):
                ref, zref, _ = rendered(mesh, faces, "tiles", clear_depth=depth_init)
                actual, z, _ = rendered(mesh, faces, "tiles-deferred",
                                        workers=2, tile_size=8, clear_depth=depth_init)
                self.assertEqual((ref, zref), (actual, z))

    def test_multiple_draw_calls_and_empty_scene(self):
        mesh, faces = stack_mesh()
        results = []
        for backend in ("tiles", "tiles-deferred"):
            fb = Framebuffer(72, 72)
            fb.clear(9, 8, 7, 6)
            raster = SoftwareRasterizer(fb, backend=backend, tile_size=8, num_threads=2)
            try:
                raster.draw_mesh([], [], VertexColorShader())
                raster.draw_mesh(mesh, faces[:4], VertexColorShader())
                raster.draw_mesh(mesh, faces[4:], VertexColorShader())
                results.append((fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()))
            finally:
                raster.executor.shutdown(wait=True)
        self.assertEqual(results[0], results[1])

    def test_stateful_or_patched_shader_rejected_before_framebuffer_write(self):
        mesh, faces = stack_mesh()
        for shader in (StatefulShader(), VertexColorShader()):
            if isinstance(shader, VertexColorShader):
                shader.fragment_shader_batch = lambda *a: np.zeros((1, 4), dtype=np.uint8)
            fb = Framebuffer(32, 32)
            fb.clear(10, 20, 30, 40)
            before = (fb.color_buffer.tobytes(), fb.depth_buffer.tobytes())
            raster = SoftwareRasterizer(fb, backend="tiles-deferred", num_threads=1)
            try:
                with self.assertRaisesRegex(ValueError, "DEFERRED_SHADER_NOT_PURE"):
                    raster.draw_mesh(mesh, faces, shader)
            finally:
                raster.executor.shutdown(wait=True)
            self.assertEqual(before, (fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()))


if __name__ == "__main__":
    unittest.main()
