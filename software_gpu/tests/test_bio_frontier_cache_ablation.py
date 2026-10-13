"""Compile and execute real C++17 bio-frontier ablations, exact framebuffer parity."""
import os
import tempfile
import unittest

from software_gpu.research.bio_workrooms import ABLATIONS, build_bio_workrooms, run_bio_workrooms
from software_gpu.research.workrooms import descriptor
from software_gpu.tests.test_bio_workrooms import sparse_scene
from software_gpu.tests.test_workrooms import renderer_oracle, scene_fixture


@unittest.skipUnless(os.environ.get('ARE_BIO_CACHE_ABLATION_TEST') == '1',
                     'Dedicated native cache-ablation CI job')
class TestBioFrontierAblations(unittest.TestCase):
    def test_unknown_variant_rejected_before_file_access(self):
        with self.assertRaisesRegex(ValueError, "ROOM_ABLATION_UNKNOWN"):
            build_bio_workrooms("not-a-directory", ablation="../../untrusted")

    def test_real_native_variants_match_python_oracle_across_workers(self):
        cases = [(31,29,4,1,scene_fixture()), (31,29,4,2,scene_fixture()),
                 (37,35,1,4,sparse_scene()), (19,17,4,8,sparse_scene())]
        with tempfile.TemporaryDirectory(prefix="are-frontier-ablation-") as tmp:
            for name in ABLATIONS:
                with self.subTest(ablation=name):
                    exe, build = build_bio_workrooms(f"{tmp}/{name}", ablation=name)
                    self.assertEqual(build["ablation"], name)
                    self.assertEqual(len(build["binary_sha256"]), 64)
                    for width,height,tile,workers,scene in cases:
                        with self.subTest(ablation=name,tile=tile,workers=workers):
                            expected_resolved, expected_final = renderer_oracle(width,height,scene)
                            result = run_bio_workrooms(exe,descriptor(width,height,tile,17),
                                                       scene,workers,2,"combined")
                            self.assertEqual(result["resolved"],expected_resolved.color_buffer.tobytes())
                            self.assertEqual(result["rgba"],expected_final.color_buffer.tobytes())
                            self.assertEqual(result["depth"],expected_final.depth_buffer.astype("<f4").tobytes())
                            self.assertEqual(result["receipt"]["workers"],workers)
                            self.assertTrue(result["receipt"]["handoff_ready"])

    def test_static_frontier_uses_disjoint_chunks_and_matches_oracle(self):
        self.assertEqual(ABLATIONS["default"], ())
        self.assertEqual(ABLATIONS["static-frontier-chunks"],
                         ("-DARE_BIO_STATIC_FRONTIER_CHUNKS=1",))
        width, height, tile = 40, 32, 1
        scene = sparse_scene()
        reference, final = renderer_oracle(width, height, scene)
        n_tiles = width * height
        n_chunks = (n_tiles + 31) // 32
        with tempfile.TemporaryDirectory(prefix="are-static-frontier-") as tmp:
            executable, build = build_bio_workrooms(tmp, ablation="static-frontier-chunks")
            self.assertEqual(build["flags"][-1], "-DARE_BIO_STATIC_FRONTIER_CHUNKS=1")
            for workers in (1, 2, 4, 8):
                with self.subTest(workers=workers):
                    out = run_bio_workrooms(executable, descriptor(width, height, tile, 17),
                                            scene, workers, 3, "combined")
                    expected = [sum(min(32, n_tiles - chunk * 32)
                                    for chunk in range(w, n_chunks, workers))
                                for w in range(workers)]
                    self.assertEqual(out["receipt"]["waves"][1]["worker_jobs"], expected)
                    self.assertEqual(out["resolved"], reference.color_buffer.tobytes())
                    self.assertEqual(out["rgba"], final.color_buffer.tobytes())
                    self.assertEqual(out["depth"],
                                     final.depth_buffer.astype("<f4").tobytes())
                    self.assertTrue(out["receipt"]["handoff_ready"])


class TestBioFrontierReceiptReadback(unittest.TestCase):
    """Signed report mutations must not certify fabricated benchmark summaries.

    These are pure receipt-contract tests, NOT performance or raster evidence.
    The native shader/framebuffer oracle runs in TestBioFrontierAblations.
    """

    def _report(self, workers=(1,)):
        from tools.benchmark_frontier_alternating import (
            CASES, PROTOCOL, VARIANTS, canonical, digest, order_for_pair,
        )
        cases = []
        for name, pixels, tile, factory in CASES:
            for worker in workers:
                pairs = [
                    {
                        "pair": i,
                        "order": list(order_for_pair(i)),
                        "measured_ms": {"default": 3.0, "static-frontier-chunks": 2.0},
                        "cpu_ms": {"default": 1.0, "static-frontier-chunks": 1.0},
                    }
                    for i in range(15)
                ]
                cases.append({
                    "scene": name, "workers": worker, "pixels": pixels,
                    "tile": tile, "triangles": len(factory()),
                    "request_sha256": "a" * 64,
                    "image_depth_sha256": "b" * 64,
                    "pairs": pairs,
                    "median_default_ms": 3.0,
                    "median_static_ms": 2.0,
                    "median_paired_delta_ms": -1.0,
                    "median_paired_static_over_default": 2.0 / 3.0,
                    "faster_static_pairs": 15,
                })
        report = {
            "protocol": PROTOCOL, "status": "PASS",
            "variants": list(VARIANTS),
            "builds": {variant: {} for variant in VARIANTS},
            "repeats": 15, "workers": list(workers), "cases": cases,
        }
        report["report_sha256"] = digest(canonical(report))
        return report

    @staticmethod
    def _resign(report):
        from tools.benchmark_frontier_alternating import canonical, digest
        report["report_sha256"] = digest(canonical({
            k: v for k, v in report.items() if k != "report_sha256"
        }))

    def test_reference_receipt_passes_integrity_gate(self):
        from tools.benchmark_frontier_alternating import verify_report
        self.assertTrue(verify_report(self._report()))

    def test_re_signed_inaccurate_summaries_are_rejected(self):
        from tools.benchmark_frontier_alternating import verify_report
        for key, bad in (
            ("median_default_ms", 30.0),
            ("median_static_ms", 20.0),
            ("faster_static_pairs", 0),
        ):
            with self.subTest(field=key):
                report = self._report()
                report["cases"][0][key] = bad
                self._resign(report)
                with self.assertRaisesRegex(ValueError, "ABBA_SUMMARY_MISMATCH"):
                    verify_report(report)

    def test_re_signed_scene_metadata_drift_is_rejected(self):
        from tools.benchmark_frontier_alternating import verify_report
        for key, bad in (("pixels", 512), ("tile", 8), ("triangles", 999)):
            with self.subTest(field=key):
                report = self._report()
                report["cases"][0][key] = bad
                self._resign(report)
                with self.assertRaisesRegex(ValueError, "ABBA_CASE_METADATA"):
                    verify_report(report)

    def test_re_signed_cross_worker_request_drift_is_rejected(self):
        from tools.benchmark_frontier_alternating import verify_report
        report = self._report(workers=(1, 2))
        report["cases"][1]["request_sha256"] = "c" * 64
        self._resign(report)
        with self.assertRaisesRegex(ValueError, "ABBA_REQUEST_DRIFT"):
            verify_report(report)

    def test_re_signed_invalid_digest_encoding_is_rejected(self):
        from tools.benchmark_frontier_alternating import verify_report
        report = self._report()
        report["cases"][0]["image_depth_sha256"] = "z" * 64
        self._resign(report)
        with self.assertRaisesRegex(ValueError, "ABBA_FRAME_HASH"):
            verify_report(report)
