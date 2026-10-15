"""Independent opt-in adaptive selection and actual CPU framebuffer regressions."""
import json
import unittest

import numpy as np

from software_gpu.benchmarks.compare_surface_plans import make_fixture, measure_scene, procedural_scene
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.surface_plan import (
    ADAPTIVE_PLAN_POLICY, DEFAULT_PLAN_POLICY, SurfacePlanPolicy,
)


def render(mesh, faces, *, backend="tiles", shader=None, pixels=96, workers=1, policy=None):
    fb = Framebuffer(pixels, pixels)
    fb.clear(16, 25, 38, 255, depth=1.)
    raster = SoftwareRasterizer(fb, backend=backend, num_threads=workers, plan_policy=policy)
    try:
        raster.draw_mesh(mesh, faces, shader if shader is not None else VertexColorShader())
        return fb, raster.last_plan_receipt
    finally:
        raster.executor.shutdown(wait=True)


class StatefulShader(VertexColorShader):
    batch_fragment_equivalent_to = None

    def __init__(self):
        self.calls = []

    def fragment_shader(self, varyings):
        self.calls.append(varyings["color"].tobytes())
        return len(self.calls) % 256, 17, 29, 127


class TestAdaptiveSurfacePlan(unittest.TestCase):
    def assert_frames_equal(self, expected, actual):
        np.testing.assert_array_equal(expected.color_buffer, actual.color_buffer)
        np.testing.assert_array_equal(expected.depth_buffer, actual.depth_buffer)

    def test_large_surfaces_select_batch_first_without_corner_scan(self):
        mesh, faces = make_fixture(8, .8)
        baseline, _ = render(mesh, faces)
        candidate, receipt = render(mesh, faces, backend="tiles-plan", policy=ADAPTIVE_PLAN_POLICY)
        self.assert_frames_equal(baseline, candidate)
        self.assertEqual(receipt["policy"], "adaptive-geometry-v1")
        self.assertEqual(receipt["selector"], "pre-draw-geometry-v1")
        self.assertEqual(receipt["selected_route"], "batch-first")
        self.assertEqual(receipt["decision"], "planned")
        self.assertGreater(receipt["counts"]["batch_fragment_samples"], 0)
        self.assertEqual(receipt["counts"]["corner_edge_evaluations"], 0)
        self.assertEqual(receipt["counts"]["scan_bypassed"], receipt["binned_pairs"])

    def test_many_small_triangles_use_reference_before_rasterization(self):
        mesh, faces = make_fixture(160, .05)
        baseline, _ = render(mesh, faces)
        candidate, receipt = render(mesh, faces, backend="tiles-plan", policy=ADAPTIVE_PLAN_POLICY)
        self.assert_frames_equal(baseline, candidate)
        self.assertEqual(receipt["selected_route"], "tiles-reference")
        self.assertEqual(receipt["reason"], "adaptive-insufficient-bbox")
        self.assertEqual(receipt["decision"], "tiles-reference")
        self.assertIsNone(receipt["counts"])

    def test_high_triangle_count_avoids_expensive_policy_even_if_large(self):
        mesh, faces = make_fixture(300, .2)
        baseline, _ = render(mesh, faces, pixels=48)
        candidate, receipt = render(mesh, faces, backend="tiles-plan", policy=ADAPTIVE_PLAN_POLICY, pixels=48)
        self.assert_frames_equal(baseline, candidate)
        self.assertEqual(receipt["selected_route"], "tiles-reference")
        self.assertEqual(receipt["reason"], "adaptive-dense-triangle-count")

    def test_dense_fallback_omits_unneeded_feature_scan(self):
        mesh, faces = make_fixture(300, .2)
        baseline, _ = render(mesh, faces, pixels=48)
        candidate, receipt = render(mesh, faces, backend="tiles-plan", pixels=48,
                                    policy=ADAPTIVE_PLAN_POLICY)
        self.assert_frames_equal(baseline, candidate)
        self.assertEqual(receipt["reason"], "adaptive-dense-triangle-count")
        self.assertEqual(receipt["decision"], "tiles-reference")
        self.assertIsNone(receipt["estimated_bbox_samples"])
        self.assertNotIn("binned_pairs", receipt)
        self.assertNotIn("small_pairs", receipt)
        self.assertFalse(receipt["adaptive_gate_metrics_available"])

    def test_dense_fallback_cache_and_uncached_have_identical_receipts(self):
        # Preparation-cache bins use the original policy key, but must not
        # leak unused gate metrics into a reference-fallback receipt.
        mesh, faces = make_fixture(300, .2)
        reference, _ = render(mesh, faces, pixels=48)
        uncached, expected = render(mesh, faces, pixels=48, backend="tiles-plan",
                                    policy=ADAPTIVE_PLAN_POLICY)
        self.assert_frames_equal(reference, uncached)
        cached_fb = Framebuffer(48, 48)
        renderer = SoftwareRasterizer(cached_fb, backend="tiles-plan", num_threads=2,
                                      plan_policy=ADAPTIVE_PLAN_POLICY,
                                      preparation_cache_bytes=8 << 20)
        try:
            for expected_cache_status in ("miss", "hit"):
                cached_fb.clear(16, 25, 38, 255, depth=1.)
                renderer.draw_mesh(mesh, faces, VertexColorShader())
                self.assert_frames_equal(reference, cached_fb)
                self.assertEqual(renderer.last_plan_receipt, expected)
                self.assertEqual(renderer.last_preparation_receipt["status"],
                                 expected_cache_status)
        finally:
            renderer.executor.shutdown(wait=True)

    def test_nonbatch_shader_preserves_scalar_side_effects(self):
        mesh, faces = make_fixture(8, .8)
        old, new = StatefulShader(), StatefulShader()
        baseline, _ = render(mesh, faces, shader=old, pixels=64)
        candidate, receipt = render(mesh, faces, shader=new, backend="tiles-plan",
                                    policy=ADAPTIVE_PLAN_POLICY, pixels=64)
        self.assert_frames_equal(baseline, candidate)
        self.assertEqual(old.calls, new.calls)
        self.assertGreater(len(new.calls), 0)
        self.assertEqual(receipt["selected_route"], "tiles-reference")
        self.assertEqual(receipt["reason"], "adaptive-no-batch-equivalence")

    def test_holdout_parity_with_multiple_workers_and_nonbenchmark_geometry(self):
        for mesh, faces in (make_fixture(6, .65), procedural_scene(7, 14)):
            baseline, _ = render(mesh, faces, pixels=64)
            single, first = render(mesh, faces, backend="tiles-plan",
                                   policy=ADAPTIVE_PLAN_POLICY, pixels=64, workers=1)
            parallel, second = render(mesh, faces, backend="tiles-plan",
                                      policy=ADAPTIVE_PLAN_POLICY, pixels=64, workers=4)
            self.assert_frames_equal(baseline, single)
            self.assert_frames_equal(baseline, parallel)
            self.assertEqual(first, second)

    def test_nonbatch_tensor_and_zero_dimensional_varyings_preserve_shapes(self):
        # Regression for the compact 1-D adaptive reference interpolation:
        # scalar ndarrays and rank-2 tensors still use generalized broadcasting.
        from software_gpu.tests.test_surface_plan import TensorShader
        mesh, faces = make_fixture(8, .8)
        baseline, _ = render(mesh, faces, backend="tiles-plan", shader=TensorShader(), pixels=64)
        actual, receipt = render(mesh, faces, backend="tiles-plan", shader=TensorShader(),
                                 pixels=64, policy=ADAPTIVE_PLAN_POLICY)
        self.assert_frames_equal(baseline, actual)
        self.assertEqual(receipt["selected_route"], "tiles-reference")
        self.assertEqual(receipt["reason"], "adaptive-no-batch-equivalence")

    def test_explicit_opt_in_does_not_change_existing_policy_receipts(self):
        mesh, faces = make_fixture(3, .6)
        default, prior = render(mesh, faces, backend="tiles-plan", pixels=48)
        explicit, after = render(mesh, faces, backend="tiles-plan", pixels=48,
                                 policy=DEFAULT_PLAN_POLICY)
        self.assert_frames_equal(default, explicit)
        self.assertEqual(prior, after)
        self.assertNotIn("selected_route", prior)

    def test_invalid_selection_fails_closed(self):
        for selector in ("random", "", None, 1):
            with self.subTest(selector=selector), self.assertRaisesRegex(
                    ValueError, "SURFACE_PLAN_POLICY_INVALID"):
                SurfacePlanPolicy(selection=selector)

    def test_real_adaptive_benchmark_provides_raw_repeats_and_receipt(self):
        mesh, faces = make_fixture(4, .65)
        result = measure_scene("independent-holdout", mesh, faces, 48, 2, 2, adaptive=True)
        self.assertTrue(result["byte_identical"])
        self.assertEqual(len(result["samples_ms"]["adaptive"]), 2)
        self.assertEqual(result["plans"]["adaptive"]["selector"], "pre-draw-geometry-v1")
        self.assertIn(result["plans"]["adaptive"]["selected_route"],
                      ("batch-first", "tiles-reference"))


if __name__ == "__main__":
    unittest.main()
