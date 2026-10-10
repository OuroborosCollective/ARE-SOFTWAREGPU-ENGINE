"""Real regressions for local policies, calibration counters and bounded CLI."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

import numpy as np
from software_gpu.benchmarks import compare_surface_plans as benchmark
from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.surface_plan import SurfacePlanPolicy, BATCH_FIRST_POLICY, COUNTERS, COUNTER_UNITS
from software_gpu.graphics.tile_backend import _pair_features, rasterize_tiles


class CountingShader(VertexColorShader):
    def __init__(self):
        self.scalar_calls = self.batch_calls = self.batch_samples = 0

    def fragment_shader(self, varyings):
        self.scalar_calls += 1
        return super().fragment_shader(varyings)

    batch_fragment_equivalent_to = fragment_shader

    def fragment_shader_batch(self, varyings):
        self.batch_calls += 1
        self.batch_samples += len(varyings["color"])
        return super().fragment_shader_batch(varyings)


class TestCalibration(unittest.TestCase):
    def test_shipped_offline_examples_activate_the_measured_profile(self):
        from software_gpu.integrations.aurion.offline_render_worker import validate_job, run_job
        root = Path(__file__).resolve().parents[2]
        jobs = [json.loads((root / "fixtures/aurion/phase4_offline" / name).read_text())
                for name in ("job.example.json", "job.scene5k.example.json")]
        for job in jobs:
            validate_job(job)
            self.assertEqual(job["render"]["backend"], "tiles-plan")
        with tempfile.TemporaryDirectory() as folder:
            receipt = run_job(jobs[0], out_dir=folder)
            plan = receipt["outcome"]["surface_plan"]
            self.assertEqual(plan["policy"], "batch-first-v1")
            self.assertEqual(plan["counts"]["corner_edge_evaluations"], 0)
            self.assertTrue(receipt["outcome"]["repeat_byte_identical"])

    def test_bounded_pair_features_against_independent_tile_rectangles(self):
        rng = np.random.default_rng(123491)
        for _ in range(500):
            x0, y0 = rng.integers(0, 100, size=2)
            x1, y1 = (x0, y0) + rng.integers(0, 150, size=2)
            tile = int(rng.choice([1, 4, 8, 16, 32, 64, 256]))
            threshold = int(rng.choice([1, 8, 64, 100, sys.maxsize]))
            rects = [(min(x1, left + tile - 1) - max(x0, left) + 1)
                     * (min(y1, top + tile - 1) - max(y0, top) + 1)
                     for top in range(0, int(y1) + 1, tile)
                     for left in range(0, int(x1) + 1, tile)
                     if min(x1, left + tile - 1) >= max(x0, left)
                     and min(y1, top + tile - 1) >= max(y0, top)]
            self.assertEqual(_pair_features(int(x0), int(x1), int(y0), int(y1), tile, threshold),
                             (len(rects), sum(n < threshold for n in rects)))

    def test_policy_validates_and_is_immutable(self):
        self.assertEqual(BATCH_FIRST_POLICY.draw_min_bbox_samples_per_triangle, 64)
        for kwargs in ({"scan_min_samples": 0}, {"batch_min_samples": False},
                       {"draw_min_bbox_samples_per_triangle": -1}, {"name": ""}, {"name": "x" * 65}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SurfacePlanPolicy(**kwargs)
        with self.assertRaises(FrozenInstanceError):
            BATCH_FIRST_POLICY.scan_min_samples = 1
        with self.assertRaises(ValueError):
            SoftwareRasterizer(Framebuffer(8, 8), backend="tiles", plan_policy=BATCH_FIRST_POLICY)
        with self.assertRaises(ValueError):
            rasterize_tiles(Framebuffer(1, 1), [], VertexColorShader(), 1, None, 1,
                            planned=True, plan_policy={})

    def test_counters_equal_actual_shader_calls_and_samples(self):
        mesh, faces = make_fixture(3, .8)
        fb = Framebuffer(64, 64)
        shader = CountingShader()
        engine = SoftwareRasterizer(fb, backend="tiles-plan", num_threads=1, tile_size=4)
        try:
            engine.draw_mesh(mesh, faces, shader)
            p = engine.last_plan_receipt
        finally:
            engine.executor.shutdown(wait=True)
        c = p["counts"]
        self.assertEqual(c["scalar_fragment_calls"], shader.scalar_calls)
        self.assertEqual(c["batch_fragment_calls"], shader.batch_calls)
        self.assertEqual(c["batch_fragment_samples"], shader.batch_samples)
        self.assertEqual(c["shaded_samples"], shader.scalar_calls + shader.batch_samples)
        self.assertEqual(p["binned_pairs"], sum(c[k] for k in ("inside", "outside", "boundary", "scan_bypassed")))
        self.assertEqual(p["small_pairs"], c["scan_bypassed"])
        self.assertEqual(set(COUNTERS), set(COUNTER_UNITS))
        self.assertEqual(p["counter_units"]["scalar_fragment_calls"], "invocation")

    def test_policies_do_not_leak_between_concurrent_renderers(self):
        mesh, faces = make_fixture(3, .8)
        def draw(policy):
            fb = Framebuffer(64, 64)
            engine = SoftwareRasterizer(fb, backend="tiles-plan", num_threads=2, plan_policy=policy)
            try:
                engine.draw_mesh(mesh, faces, VertexColorShader())
                return fb.color_buffer.tobytes(), fb.depth_buffer.tobytes(), engine.last_plan_receipt
            finally:
                engine.executor.shutdown(wait=True)
        with ThreadPoolExecutor(2) as pool:
            a = pool.submit(draw, SurfacePlanPolicy())
            b = pool.submit(draw, BATCH_FIRST_POLICY)
            a, b = a.result(), b.result()
        self.assertEqual(a[:2], b[:2])
        self.assertEqual(a[2]["scan_min_samples"], 64)
        self.assertEqual(b[2]["scan_min_samples"], sys.maxsize)
        self.assertGreater(a[2]["counts"]["corner_edge_evaluations"], 0)
        self.assertEqual(b[2]["counts"]["corner_edge_evaluations"], 0)

    def test_fallback_still_exposes_features_without_fabricated_execution_counts(self):
        mesh, faces = make_fixture(1, .03)
        result = benchmark.measure_scene("tiny", mesh, faces, 32, 1, 1)
        p = result["plans"]["plan-batch"]
        self.assertIsNone(p["counts"])
        self.assertGreater(p["binned_pairs"], 0)
        self.assertEqual(p["small_pairs"], p["binned_pairs"])
        fb = Framebuffer(32, 32)
        renderer = SoftwareRasterizer(fb, backend="tiles-plan", num_threads=1,
                                      plan_policy=BATCH_FIRST_POLICY)
        try:
            renderer.draw_mesh(mesh, faces, VertexColorShader())
            self.assertEqual(renderer.last_plan_receipt["decision"], "tiles-reference")
            self.assertIsNone(renderer.last_plan_receipt["counts"])
        finally:
            renderer.executor.shutdown(wait=True)

    def test_real_ablation_and_both_direction_guards(self):
        mesh, faces = make_fixture(3, .8)
        result = benchmark.measure_scene("ablation", mesh, faces, 64, 1, 2, ablation=True)
        self.assertEqual(len(result["samples_ms"]), 8)
        self.assertTrue(result["byte_identical"])
        p = result["plans"]["abl-noscan-batch"]
        with self.assertRaisesRegex(AssertionError, "ABLATION_NOT_APPLIED"):
            benchmark.check_overrides("scan", p, {"scan": True, "force": True})
        with self.assertRaisesRegex(AssertionError, "ABLATION_NOT_APPLIED"):
            benchmark.check_overrides("missing", None, {"scan": False, "force": True})
        bad = dict(p, draw_min_bbox_samples_per_triangle=64)
        with self.assertRaisesRegex(AssertionError, "ABLATION_NOT_APPLIED"):
            benchmark.check_overrides("gate", bad, {"scan": False, "force": True})
        bad = dict(p, counts=dict(p["counts"], corner_edge_evaluations=12))
        with self.assertRaisesRegex(AssertionError, "ABLATION_NOT_APPLIED"):
            benchmark.check_overrides("execution", bad, {"scan": False, "force": True})

    def test_statistics_and_fixture_seed_contract(self):
        self.assertEqual(benchmark.summarize([1, 2, 3, 4, 100]),
                         {"n": 5, "median": 3., "iqr": 2., "mad": 1., "min": 1., "max": 100.})
        self.assertEqual(benchmark.SCENES[0][1]["seed"], 1234)
        with self.assertRaises(ValueError):
            benchmark.build_scene({"kind": "fixture", "seed": 1, "triangles": 1, "size": .03})
        env = benchmark.environment()
        self.assertTrue(env["cpu_model"])
        self.assertIn("numpy_build", env)

    def test_cli_rejects_nonfinite_budget_and_expanded_invalid_bounds(self):
        for args in (["--max-seconds", "nan"], ["--max-seconds", "inf"], ["--max-seconds", "-1"],
                     ["--repeats", "31"], ["--pixels", "1025"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                benchmark.main(["--output-dir", "unused"] + args)
            self.assertEqual(error.exception.code, 2)

    def test_actual_subprocess_budget_publishes_no_partial_files(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "result"
            with self.assertRaisesRegex(RuntimeError, "BUDGET_EXCEEDED"):
                benchmark.main(["--output-dir", str(output), "--pixels", "32", "--repeats", "1",
                                "--max-seconds", "0.01"])
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_actual_budgeted_cli_exports_complete_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            benchmark.main(["--output-dir", folder, "--pixels", "32", "--repeats", "1"])
            receipt = json.loads((Path(folder) / "surface-plan-benchmark.json").read_text())
            self.assertEqual(len(receipt["results"]), 5)
            self.assertTrue(all(r["byte_identical"] for r in receipt["results"]))
            self.assertIn("benchmark_source_sha256", receipt)
            self.assertIn("fixture_source_sha256", receipt)

    def test_inline_expired_deadline(self):
        mesh, faces = make_fixture(1, .03)
        with self.assertRaisesRegex(RuntimeError, "BUDGET_EXCEEDED"):
            benchmark.measure_scene("expired", mesh, faces, 32, 1, 1, deadline=time.monotonic() - 1)

    def test_explicit_unbounded_cli_exports_real_ablation(self):
        with tempfile.TemporaryDirectory() as folder:
            benchmark.main(["--output-dir", folder, "--pixels", "32", "--repeats", "1",
                            "--ablation", "--max-seconds", "0"])
            receipt = json.loads((Path(folder) / "surface-plan-benchmark.json").read_text())
            self.assertEqual(receipt["budget_seconds"], 0)
            self.assertTrue(all(len(r["samples_ms"]) == 8 and r["byte_identical"] for r in receipt["results"]))

    def test_new_valid_upper_cli_bounds_reach_the_real_budget_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "BUDGET_EXCEEDED"):
                benchmark.main(["--output-dir", folder, "--pixels", "1024", "--repeats", "30",
                                "--max-seconds", "0.01"])
