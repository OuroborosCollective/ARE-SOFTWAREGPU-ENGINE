"""#287: real CPU tile shader/depth provenance; no mock raster or runtime."""
import copy
import unittest

import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex
from software_gpu.graphics.pixel_trace import PixelForensicTrace, inspect_trace_receipt


REVISION = "c854a745356ec05b7c4a9b34b6a6a3c60cd2b094"
TRI = [(-0.8, -0.8, 0.4), (0.8, -0.8, 0.4), (0.0, 0.8, 0.4)]


class CountingAlphaShader:
    def __init__(self):
        self.calls = 0

    def vertex_shader(self, vertex):
        return np.asarray(vertex.position, dtype=np.float64), {
            "color": np.asarray(vertex.color, dtype=np.float64),
            "alpha": int(vertex.uv[0]),
        }

    def fragment_shader(self, varyings):
        self.calls += 1
        c = np.clip(varyings["color"] * 255, 0, 255)
        return int(c[0]), int(c[1]), int(c[2]), varyings["alpha"]


def triangle(points=TRI, color=(1, 0, 0), alpha=255):
    return [
        Vertex(np.array([x, y, z, 1.0]), color=np.asarray(color, dtype=np.float64),
               uv=np.array([alpha, 0.0]))
        for x, y, z in points
    ]


def execute(draws, traced, workers=1, quota=32):
    fb = Framebuffer(64, 64)
    fb.clear(4, 5, 6, 255, 1.0)
    shader = CountingAlphaShader()
    raster = SoftwareRasterizer(fb, num_threads=workers, tile_size=16)
    trace = PixelForensicTrace(fb, 32, 32, REVISION, max_events=quota) if traced else None
    try:
        for vertices, indices in draws:
            if traced:
                raster.draw_mesh_traced(vertices, indices, shader, trace)
            else:
                raster.draw_mesh(vertices, indices, shader)
        result = trace.finish() if traced else None
    finally:
        raster.executor.shutdown(wait=True)
    return fb, shader.calls, result


class PixelForensicTests(unittest.TestCase):
    def assert_identical(self, draws, workers=1):
        reference, ref_calls, _ = execute(draws, False, workers)
        traced, trace_calls, receipt = execute(draws, True, workers)
        self.assertEqual(reference.color_buffer.tobytes(), traced.color_buffer.tobytes())
        self.assertEqual(reference.depth_buffer.tobytes(), traced.depth_buffer.tobytes())
        self.assertEqual(ref_calls, trace_calls)
        self.assertEqual(receipt["full_frame_rgba_sha256"],
                         __import__("hashlib").sha256(traced.color_buffer.tobytes()).hexdigest())
        self.assertEqual(receipt["full_frame_depth_sha256"],
                         __import__("hashlib").sha256(traced.depth_buffer.tobytes()).hexdigest())
        self.assertTrue(receipt["complete"])
        self.assertIn("Pixel", inspect_trace_receipt(receipt))
        return receipt

    def test_two_overlapping_triangles_and_equal_depth_owner(self):
        verts = triangle(color=(1, 0, 0)) + triangle(color=(0, 0, 1))
        receipt = self.assert_identical([(verts, [(0, 1, 2), (3, 4, 5)])], workers=2)
        events = receipt["events"]
        self.assertEqual([e["primitive_id"] for e in events], [0, 1])
        self.assertEqual([e["decision"] for e in events], ["shader_call", "depth_reject"])
        self.assertEqual(receipt["final_rgba"], [254, 0, 0, 255])
        self.assertEqual(receipt["final_owner"], {"draw_id": 0, "primitive_id": 0, "raster_triangle_id": 0})
        self.assertEqual(sum(int(e["shader_called"]) for e in events), 1)

    def test_nearer_later_triangle_takes_ownership(self):
        verts = triangle(color=(1, 0, 0)) + triangle(
            points=[(x, y, 0.1) for x, y, _ in TRI], color=(0, 1, 0))
        receipt = self.assert_identical([(verts, [(0, 1, 2), (3, 4, 5)])])
        self.assertEqual([e["decision"] for e in receipt["events"]], ["shader_call", "shader_call"])
        self.assertEqual(receipt["final_owner"]["primitive_id"], 1)
        self.assertEqual(receipt["final_rgba"], [0, 254, 0, 255])

    def test_transparent_triangle_still_writes_depth(self):
        verts = triangle(alpha=0) + triangle(color=(0, 1, 0))
        receipt = self.assert_identical([(verts, [(0, 1, 2), (3, 4, 5)])])
        self.assertEqual(receipt["final_rgba"], [254, 0, 0, 0])
        self.assertEqual(receipt["events"][1]["decision"], "depth_reject")

    def test_nan_discard_and_edge_rejection(self):
        invalid = triangle(color=(0, 0, 1))
        invalid[0].position[0] = np.nan
        away = triangle(points=[(-0.9, -0.9, 0.2), (-0.4, -0.9, 0.2),
                                (-0.65, -0.4, 0.2)], color=(0, 1, 0))
        verts = invalid + away + triangle()
        receipt = self.assert_identical([(verts, [(0, 1, 2), (3, 4, 5), (6, 7, 8)])])
        self.assertIn(0, receipt["discarded_primitives"][0])
        self.assertEqual(receipt["final_owner"]["primitive_id"], 2)

    def test_inside_candidate_bounds_but_outside_edge_rejected(self):
        # Triangle bounding rectangle contains (32,32), actual edge test does not.
        points = [(-0.625, -0.78125, 0.3), (0.78125, -0.78125, 0.3),
                  (0.8125, 0.8125, 0.3)]
        vertices = triangle(points=points, color=(0, 0, 1)) + triangle()
        receipt = self.assert_identical([(vertices, [(0, 1, 2), (3, 4, 5)])], workers=2)
        self.assertEqual(receipt["events"][0]["decision"], "edge_reject")
        self.assertFalse(receipt["events"][0]["edge_pass"])
        self.assertEqual(len(receipt["events"][0]["edge_f32_bits"]), 3)
        self.assertEqual(receipt["final_owner"]["primitive_id"], 1)

    def test_near_clipped_source_provenance_and_draw_sequence(self):
        near = triangle(points=[(-0.8, -0.8, -1.5), (0.8, -0.8, 0.3),
                                (0.0, 0.8, 0.3)], color=(0, 1, 0))
        receipt = self.assert_identical([(near, [(0, 1, 2)]),
                                         (triangle(color=(1, 0, 0)), [(0, 1, 2)])])
        self.assertEqual([d["draw_id"] for d in receipt["draws"]], [0, 1])
        self.assertGreaterEqual(receipt["draws"][0]["raster_triangle_count"], 2)
        self.assertTrue(any(e["primitive_id"] == 0 and e["draw_id"] == 0
                            for e in receipt["events"]))
        self.assertEqual(len(receipt["draw_sequence_sha256"]), 64)

    def test_quota_and_unsupported_mode_fail_before_color_or_depth_writes(self):
        fb = Framebuffer(64, 64)
        fb.clear()
        colors, depths = fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()
        raster = SoftwareRasterizer(fb, num_threads=1, backend="bands")
        trace = PixelForensicTrace(fb, 32, 32, REVISION, max_events=1)
        try:
            with self.assertRaisesRegex(ValueError, "PIXEL_TRACE_BACKEND"):
                raster.draw_mesh_traced(triangle(), [(0, 1, 2)], CountingAlphaShader(), trace)
        finally:
            raster.executor.shutdown(wait=True)
        self.assertEqual(fb.color_buffer.tobytes(), colors)
        self.assertEqual(fb.depth_buffer.tobytes(), depths)
        raster = SoftwareRasterizer(fb, num_threads=1)
        try:
            with self.assertRaisesRegex(ValueError, "PIXEL_TRACE_QUOTA"):
                raster.draw_mesh_traced(triangle() + triangle(),
                                        [(0, 1, 2), (3, 4, 5)], CountingAlphaShader(), trace)
        finally:
            raster.executor.shutdown(wait=True)
        self.assertEqual(fb.color_buffer.tobytes(), colors)
        self.assertEqual(fb.depth_buffer.tobytes(), depths)

    def test_bad_pixel_budget_or_sha_and_receipt_tampering_fail_closed(self):
        fb = Framebuffer(64, 64)
        for x, y, limit, sha in [(-1, 2, 1, REVISION), (64, 0, 1, REVISION),
                                  (1, 1, 0, REVISION), (1, 1, 300, REVISION),
                                  (1, 1, 3, "unverified")]:
            with self.assertRaises(ValueError):
                PixelForensicTrace(fb, x, y, sha, max_events=limit)
        receipt = self.assert_identical([(triangle(), [(0, 1, 2)])])
        forged = copy.deepcopy(receipt)
        forged["events"][0]["decision"] = "depth_reject"
        with self.assertRaisesRegex(ValueError, "PIXEL_TRACE_DIGEST"):
            inspect_trace_receipt(forged)

    def test_exception_invalidates_receipt(self):
        class FailingShader(CountingAlphaShader):
            def fragment_shader(self, varyings):
                raise RuntimeError("real shader failure")

        fb = Framebuffer(64, 64)
        raster = SoftwareRasterizer(fb, num_threads=1)
        trace = PixelForensicTrace(fb, 32, 32, REVISION)
        try:
            with self.assertRaisesRegex(RuntimeError, "real shader failure"):
                raster.draw_mesh_traced(triangle(), [(0, 1, 2)], FailingShader(), trace)
            with self.assertRaisesRegex(ValueError, "PIXEL_TRACE_INCOMPLETE"):
                trace.finish()
            with self.assertRaisesRegex(ValueError, "PIXEL_TRACE_CLOSED"):
                raster.draw_mesh_traced(triangle(), [(0, 1, 2)], CountingAlphaShader(), trace)
        finally:
            raster.executor.shutdown(wait=True)

    def test_sealed_trace_refuses_untracked_draw(self):
        fb = Framebuffer(64, 64)
        shader = CountingAlphaShader()
        raster = SoftwareRasterizer(fb, num_threads=1)
        trace = PixelForensicTrace(fb, 32, 32, REVISION)
        try:
            raster.draw_mesh_traced(triangle(), [(0, 1, 2)], shader, trace)
            receipt = trace.finish()
            with self.assertRaisesRegex(ValueError, "PIXEL_TRACE_CLOSED"):
                raster.draw_mesh_traced(triangle(), [(0, 1, 2)], shader, trace)
            self.assertEqual(receipt["final_owner"]["primitive_id"], 0)
        finally:
            raster.executor.shutdown(wait=True)

    def test_depth_bits_and_call_order(self):
        near = triangle(color=(0, 1, 0))
        far = triangle(points=[(x, y, 0.8) for x, y, _ in TRI], color=(1, 0, 0))
        receipt = self.assert_identical([(near + far, [(0, 1, 2), (3, 4, 5)])])
        first, second = receipt["events"]
        self.assertEqual(first["decision"], "shader_call")
        self.assertEqual(second["decision"], "depth_reject")
        self.assertFalse(second["shader_called"])
        self.assertEqual(first["written_depth_f32_bits"], receipt["final_depth_f32_bits"])
        self.assertEqual(first["depth_rule"], "strict_less")
        self.assertTrue(all(len(value) == 8 for value in first["edge_f32_bits"]))

    def test_preparation_and_provenance_errors_cannot_be_sealed(self):
        fb = Framebuffer(64, 64)
        shader = CountingAlphaShader()
        raster = SoftwareRasterizer(fb, num_threads=1)
        first = PixelForensicTrace(fb, 32, 32, REVISION)
        empty_color, empty_depth = fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()
        try:
            with self.assertRaisesRegex(IndexError, "triangle index outside"):
                raster.draw_mesh_traced(triangle(), [(0, 1, 99)], shader, first)
            with self.assertRaisesRegex(ValueError, "PIXEL_TRACE_INCOMPLETE"):
                first.finish()
            second = PixelForensicTrace(fb, 32, 32, REVISION)
            vertices = triangle()
            vertices[0].normal = np.asarray([object()], dtype=object)
            with self.assertRaisesRegex(ValueError, "PIXEL_TRACE_UNHASHABLE_INPUT"):
                raster.draw_mesh_traced(vertices, [(0, 1, 2)], shader, second)
            with self.assertRaisesRegex(ValueError, "PIXEL_TRACE_INCOMPLETE"):
                second.finish()
        finally:
            raster.executor.shutdown(wait=True)
        self.assertEqual(shader.calls, 0)
        self.assertEqual(fb.color_buffer.tobytes(), empty_color)
        self.assertEqual(fb.depth_buffer.tobytes(), empty_depth)

    def test_default_draw_has_no_instrumentation_or_extra_shader_calls(self):
        fb, calls, receipt = execute([(triangle(), [(0, 1, 2)])], False)
        self.assertIsNone(receipt)
        self.assertGreater(calls, 0)
        self.assertEqual(tuple(int(x) for x in fb.color_buffer[32, 32]), (254, 0, 0, 255))


if __name__ == "__main__":
    unittest.main()
