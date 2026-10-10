"""Real rendering and negative contracts for the opt-in surface planner."""
import hashlib
from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.geometry import edge_covered
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex
from software_gpu.graphics.surface_plan import (
    PlanTrace, classify_tile, equivalent_batch, checked_batch_rgba, MAX_TRACE_TILES,
)
from software_gpu.graphics.tile_backend import rasterize_tiles
from software_gpu.benchmarks.compare_surface_plans import (
    ScalarColorShader, measure_scene, procedural_scene, write_report, main,
)
from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.integrations.aurion.offline_render_worker import (
    _render_mesh, build_procedural_mesh, run_job,
)


def render(mesh, faces, backend="tiles-plan", shader=None, size=64, workers=1, tile_size=16):
    fb = Framebuffer(size, size)
    fb.clear(16, 25, 38, 255, depth=1.0)
    engine = SoftwareRasterizer(fb, backend=backend, num_threads=workers, tile_size=tile_size)
    try:
        engine.draw_mesh(mesh, faces, shader if shader is not None else VertexColorShader())
        return fb, engine.last_plan_receipt
    finally:
        engine.executor.shutdown(wait=True)


def triangle(points=None):
    points = points if points is not None else [(-.9, -.9, .3, 1), (.9, -.9, .3, 1), (0, .9, .3, 1)]
    return [Vertex(np.asarray(p), color=np.asarray(c))
            for p, c in zip(points, ([.9, .1, .2], [.1, .9, .3], [.2, .3, .9]))]


class StatefulShader(ScalarColorShader):
    def __init__(self):
        self.values = []

    def fragment_shader(self, varyings):
        self.values.append(varyings["color"].tobytes())
        return len(self.values) % 256, 27, 39, 127


class TensorShader(ScalarColorShader):
    def vertex_shader(self, vertex):
        return vertex.position, {"scalar_array": np.asarray(vertex.color[0], dtype=np.float64),
                                 "matrix": np.outer(vertex.color, vertex.color).astype(np.float64),
                                 "flat": 9}

    def fragment_shader(self, varyings):
        value = int(np.clip(varyings["matrix"].sum() * 32, 0, 255))
        return value, int(varyings["scalar_array"] * 100), varyings["flat"], 127


class TestSurfacePlan(unittest.TestCase):
    def assert_buffers(self, a, b):
        np.testing.assert_array_equal(a.color_buffer, b.color_buffer)
        np.testing.assert_array_equal(a.depth_buffer, b.depth_buffer)

    def test_planned_batches_match_reference_on_real_meshes(self):
        for mesh, faces in (make_fixture(40, .15), make_fixture(3, .9), procedural_scene(6, 12)):
            reference, _ = render(mesh, faces, backend="tiles")
            for size in (8, 16, 32):
                with self.subTest(tile_size=size, triangles=len(faces)):
                    actual, plan = render(mesh, faces, tile_size=size)
                    self.assert_buffers(reference, actual)
                    self.assertEqual(plan["provider_calls"], 0)
                    if plan["counts"] is not None:
                        self.assertGreater(plan["counts"]["shaded_samples"], 0)
                    else:
                        self.assertEqual(plan["decision"], "tiles-reference")
                    self.assertEqual({n["color"] for n in plan["nodes"]},
                                     {"blue", "purple", "orange", "green"})

    def test_corner_classification_against_dense_float32(self):
        rng = np.random.default_rng(3261)
        seen = set()
        for _ in range(300):
            s0, s1, s2 = rng.uniform(-20, 40, (3, 3)).astype(np.float32)
            px = (np.arange(16, dtype=np.float32) + np.float32(.5))[None, :]
            py = (np.arange(16, dtype=np.float32) + np.float32(.5))[:, None]
            mask = np.ones((16, 16), dtype=bool)
            for a, b in ((s1, s2), (s2, s0), (s0, s1)):
                values = (px-a[0])*(b[1]-a[1]) - (py-a[1])*(b[0]-a[0])
                mask &= edge_covered(values, a, b)
            mode = classify_tile(s0, s1, s2, 0, 15, 0, 15)
            seen.add(mode)
            if mode == "outside":
                self.assertFalse(mask.any())
            elif mode == "inside":
                self.assertTrue(mask.all())
        self.assertEqual(seen, {"inside", "outside", "boundary"})

    def test_nonfinite_corners_fall_back(self):
        with np.errstate(invalid="ignore", over="ignore"):
            for bad in (np.inf, np.nan, np.finfo(np.float32).max):
                pts = np.asarray([[0, 0, 0], [bad, bad, 0], [1, 2, 0]], dtype=np.float32)
                self.assertEqual(classify_tile(*pts, 0, 31, 0, 31), "boundary")

    def test_shared_edges_depth_ties_and_alpha(self):
        mesh = [Vertex(np.asarray(p), color=np.asarray([.5, .3, .7])) for p in
                [(-1, -1, .3, 1), (1, -1, .3, 1), (1, 1, .3, 1), (-1, 1, .3, 1)]]
        faces = [(0, 1, 2), (0, 2, 3), (0, 1, 2)]
        old_shader, new_shader = StatefulShader(), StatefulShader()
        old, _ = render(mesh, faces, backend="tiles", shader=old_shader)
        new, plan = render(mesh, faces, shader=new_shader)
        self.assert_buffers(old, new)
        self.assertEqual(old_shader.values, new_shader.values)
        self.assertEqual(len(new_shader.values), 64 * 64)
        self.assertEqual(plan["counts"]["batch_fragment_calls"], 0)
        self.assertTrue(np.all(new.color_buffer[:, :, 3] == 127))

    def test_perspective_clipping_and_invalid_primitives(self):
        cases = [triangle([(-.8, -.8, .1, 1), (.8, -.8, .1, 1), (0, .7, .2, .8)]),
                 triangle([(-.8, -.8, -2, 1), (.8, -.8, .1, 1), (0, .8, .1, 1)]),
                 triangle([(-1e9, -.8, .1, 1), (.8, -.8, .1, 1), (0, .8, .1, 1)]),
                 triangle([(-.8, -.8, .1, 1), (.8, -.8, .1, 1), (0, .8, np.nan, 1)])]
        for mesh in cases:
            reference, _ = render(mesh, [(0, 1, 2)], backend="tiles")
            planned, _ = render(mesh, [(0, 1, 2)])
            self.assert_buffers(reference, planned)

    def test_tensor_and_zero_dimensional_varyings(self):
        mesh = triangle()
        reference, _ = render(mesh, [(0, 1, 2)], backend="bands", shader=TensorShader())
        planned, _ = render(mesh, [(0, 1, 2)], shader=TensorShader())
        self.assert_buffers(reference, planned)

    def test_deterministic_workers_and_bounded_graph(self):
        mesh, faces = make_fixture(50, .35)
        reference, receipt = render(mesh, faces, workers=1)
        parallel, second = render(mesh, faces, workers=4)
        self.assert_buffers(reference, parallel)
        self.assertEqual(receipt, second)
        trace = PlanTrace([(0, x) for x in range(MAX_TRACE_TILES + 1)])
        for coordinate in reversed(sorted(trace.selected)):
            trace.record(coordinate, {"inside": 1})
        plan = trace.receipt()
        self.assertTrue(plan["trace_truncated"])
        self.assertEqual(len(plan["nodes"]), 4 * MAX_TRACE_TILES)
        raw = json.dumps({k: v for k, v in plan.items() if k != "plan_sha256"},
                         sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), plan["plan_sha256"])

    def test_empty_draw_resets_receipt(self):
        fb = Framebuffer(32, 32)
        engine = SoftwareRasterizer(fb, backend="tiles-plan", num_threads=1)
        try:
            engine.draw_mesh(triangle(), [(0, 1, 2)], VertexColorShader())
            self.assertGreater(engine.last_plan_receipt["tile_count"], 0)
            engine.draw_mesh([], [], VertexColorShader())
            self.assertEqual(engine.last_plan_receipt["tile_count"], 0)
            self.assertEqual(engine.last_plan_receipt["nodes"], [])
        finally:
            engine.executor.shutdown(wait=True)

    def test_explicit_batch_opt_in_and_override_guard(self):
        self.assertIsNotNone(equivalent_batch(VertexColorShader()))
        self.assertIsNone(equivalent_batch(ScalarColorShader()))
        self.assertIsNone(equivalent_batch(StatefulShader()))
        class Override(VertexColorShader):
            def fragment_shader(self, varyings):
                return 23, 34, 45, 56
        custom = Override()
        self.assertIsNone(equivalent_batch(custom))
        reference, _ = render(triangle(), [(0, 1, 2)], backend="tiles", shader=custom)
        actual, plan = render(triangle(), [(0, 1, 2)], shader=custom)
        self.assert_buffers(reference, actual)
        self.assertEqual(plan["counts"]["batch_fragment_calls"], 0)
        custom = VertexColorShader()
        custom.fragment_shader = lambda varyings: (1, 2, 3, 4)
        self.assertIsNone(equivalent_batch(custom))

    def test_failed_geometry_does_not_reuse_old_receipt(self):
        engine = SoftwareRasterizer(Framebuffer(32, 32), backend="tiles-plan", num_threads=1)
        try:
            engine.draw_mesh(triangle(), [(0, 1, 2)], VertexColorShader())
            self.assertIsNotNone(engine.last_plan_receipt)
            with self.assertRaises(IndexError):
                engine.draw_mesh(triangle(), [(0, 1, 99)], VertexColorShader())
            self.assertIsNone(engine.last_plan_receipt)
        finally:
            engine.executor.shutdown(wait=True)

    def test_batch_rgba_negative_contracts(self):
        invalid = [None, [[1, 2, 3, 4]], np.zeros((8, 3), dtype=np.uint8),
                   np.zeros((8, 4), dtype=np.float32), np.full((8, 4), -1),
                   np.full((8, 4), 256), np.zeros((9, 4), dtype=np.uint8)]
        for value in invalid:
            with self.subTest(value_type=type(value)), self.assertRaisesRegex(ValueError, "BATCH_RGBA"):
                checked_batch_rgba(lambda attrs: value, {}, 8)
        valid = np.full((8, 4), 255, dtype=np.int64)
        self.assertEqual(checked_batch_rgba(lambda attrs: valid, {}, 8).dtype, np.uint8)

    def test_invalid_batch_does_not_write_its_tile(self):
        class Invalid(VertexColorShader):
            def fragment_shader_batch(self, varyings):
                return np.full((len(varyings["color"]), 4), 1000)
        fb = Framebuffer(32, 32)
        old_color, old_depth = fb.color_buffer.copy(), fb.depth_buffer.copy()
        engine = SoftwareRasterizer(fb, backend="tiles-plan", num_threads=1)
        try:
            with self.assertRaisesRegex(ValueError, "BATCH_RGBA"):
                engine.draw_mesh(triangle(), [(0, 1, 2)], Invalid())
            np.testing.assert_array_equal(fb.color_buffer, old_color)
            np.testing.assert_array_equal(fb.depth_buffer, old_depth)
            self.assertIsNone(engine.last_plan_receipt)
        finally:
            engine.executor.shutdown(wait=True)

    def test_shader_batch_matches_scalar_and_rejects_invalid_input(self):
        shader = VertexColorShader()
        colors = np.asarray([[-1., .5, 3.], [0., 1., .501], [.33, .67, .99]], dtype=np.float32)
        expected = np.asarray([shader.fragment_shader({"color": c}) for c in colors], dtype=np.uint8)
        np.testing.assert_array_equal(shader.fragment_shader_batch({"color": colors}), expected)
        for value in (np.zeros(3), np.zeros((8, 2)), np.full((8, 3), np.nan)):
            with self.assertRaisesRegex(ValueError, "BATCH_COLOR"):
                shader.fragment_shader_batch({"color": value})

    def test_scan_and_batch_bypass_for_small_work(self):
        mesh, faces = make_fixture(1, .03)
        _, plan = render(mesh, faces, size=32)
        self.assertEqual(plan["decision"], "tiles-reference")
        self.assertEqual(plan["reason"], "small-primitive-cost-threshold")
        self.assertIsNone(plan["counts"])

    def test_scan_and_batch_tile_thresholds(self):
        _, plan = render(triangle(), [(0, 1, 2)], tile_size=4)
        self.assertGreater(plan["counts"]["scan_bypassed"], 0)
        self.assertGreater(plan["counts"]["scalar_fragment_calls"], 0)
        self.assertGreater(plan["counts"]["batch_fragment_calls"], 0)
        self.assertEqual(plan["counts"]["corner_edge_evaluations"], 0)

    def test_jit_is_not_silently_combined(self):
        with self.assertRaisesRegex(ValueError, "PLANNED_JIT"):
            rasterize_tiles(Framebuffer(1, 1), [], VertexColorShader(), 1, None, 1,
                            compiled=True, planned=True)

    def test_real_benchmark_and_colored_report(self):
        mesh, faces = make_fixture(2, .5)
        result = measure_scene("<test>", mesh, faces, 32, 1, 1)
        self.assertTrue(result["byte_identical"])
        self.assertEqual(set(result["samples_ms"]), {"tiles", "plan-scalar", "plan-batch"})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            write_report(path, {"results": [result]})
            body = (path / "surface-plan-report.html").read_text("utf-8")
            self.assertIn("&lt;test&gt;", body)
            self.assertIn("#2563eb", body)
            self.assertEqual(json.loads((path / "surface-plan-benchmark.json").read_text())["results"][0]["scene"], "<test>")

    def test_offline_worker_planned_backend_is_real(self):
        vertices, faces = build_procedural_mesh(991, 4, 8)
        camera = {"yaw_degrees": 25., "pitch_degrees": 20., "center_y": 0.,
                  "x_half_extent": 1.6, "y_half_extent": 1.6}
        with tempfile.TemporaryDirectory() as folder:
            old = _render_mesh(vertices, faces, camera, "tiles", 32, 2, 600, Path(folder), "old")
            new = _render_mesh(vertices, faces, camera, "tiles-plan", 32, 2, 600, Path(folder), "new")
            self.assertEqual(old["replay_hash_sha256"], new["replay_hash_sha256"])
            self.assertIn("surface_plan", new)
            self.assertEqual(new["surface_plan"]["policy"], "batch-first-v1")
            if new["surface_plan"]["counts"] is not None:
                self.assertEqual(new["surface_plan"]["counts"]["corner_edge_evaluations"], 0)
            self.assertNotIn("surface_plan", old)

    def test_isolated_job_receipt_readback(self):
        from software_gpu.tests.test_aurion_offline_phase4 import make_job
        job = make_job(render={"backend": "tiles-plan", "pixels": 64})
        with tempfile.TemporaryDirectory() as folder:
            receipt = run_job(job, out_dir=folder)
            disk = json.loads((Path(folder) / "aurion-phase4-receipt.json").read_text("utf-8"))
            self.assertEqual(disk, receipt)
            self.assertEqual(receipt["authority"], "offline-read-only")
            self.assertEqual(receipt["outcome"]["surface_plan"]["provider_calls"], 0)
            self.assertEqual(receipt["outcome"]["surface_plan"]["policy"], "batch-first-v1")

    def test_wolfram_golden_has_independent_exact_readback(self):
        path = Path(__file__).resolve().parents[1] / "evidence" / "wolfram-surface-plan.v1.json"
        golden = json.loads(path.read_text("utf-8"))
        self.assertEqual(golden["authority"], "none")
        self.assertTrue(golden["affineCornerIdentity"] and golden["weightsSumToOne"])
        classes = {}
        for ty in range(0, 32, 8):
            for tx in range(0, 32, 8):
                values = [20 - Fraction(x * 2 + 1, 2) - Fraction(y * 2 + 1, 2)
                          for x in (tx, tx + 7) for y in (ty, ty + 7)]
                classes[(ty, tx)] = "inside" if min(values) >= 0 else ("outside" if max(values) < 0 else "boundary")
        counts = {name: list(classes.values()).count(name) for name in ("inside", "outside", "boundary")}
        reference, optimized = [], []
        for y in range(32):
            for x in range(32):
                inside = 20 - Fraction(x * 2 + 1, 2) - Fraction(y * 2 + 1, 2) >= 0
                reference.append(inside)
                mode = classes[(y // 8 * 8, x // 8 * 8)]
                optimized.append(inside if mode == "boundary" else mode == "inside")
        self.assertEqual(reference, optimized)
        self.assertEqual(counts, golden["tileCounts"])
        self.assertEqual(sum(reference), golden["coveredPixels"])
        self.assertEqual(64 + 64 * counts["boundary"], golden["optimizedEdgeEvaluations"])

    def test_tensor_varyings_work_after_small_draw_fallback(self):
        mesh, faces = make_fixture(1, .03)
        reference, _ = render(mesh, faces, backend="bands", shader=TensorShader())
        planned, plan = render(mesh, faces, shader=TensorShader())
        self.assert_buffers(reference, planned)
        self.assertEqual(plan["decision"], "tiles-reference")

    def test_benchmark_cli_argument_limits(self):
        for args in (["--repeats", "0"], ["--pixels", "10"], ["--workers", "17"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                main(["--output-dir", "unused"] + args)
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
