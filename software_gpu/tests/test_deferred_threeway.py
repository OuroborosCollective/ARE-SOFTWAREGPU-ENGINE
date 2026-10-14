"""Real rendering and integrity rules for the three-way CPU research control.

Parity tests are NOT performance benchmarks. No synthetic timings establish
a speedup; actual 15-pair data are produced by a separate native CI job.
"""
import unittest

from software_gpu.benchmarks.compare_deferred_threeway import (
    SCENES, VARIANTS, make_scene, measure_one, order_for_pair,
    summarize, validate_report,
)


class TestDeferredThreeWay(unittest.TestCase):
    def test_existing_scalar_batch_first_and_deferred_render_same_frame(self):
        # The policy must really batch; otherwise this is not a fair control.
        for layers, order in SCENES:
            mesh, faces = make_scene(layers, order)
            for workers in (1, 2):
                with self.subTest(layers=layers, order=order, workers=workers):
                    reference = None
                    for variant in VARIANTS:
                        elapsed, hashes, details = measure_one(
                            mesh, faces, variant, pixels=64, workers=workers
                        )
                        self.assertGreater(elapsed, 0.0)
                        if reference is None:
                            reference = hashes
                        self.assertEqual(reference, hashes)
                        if variant == "batch-first":
                            self.assertEqual(details["decision"], "planned")
                            self.assertEqual(details["policy"], "batch-first-v1")
                            self.assertGreater(details["batch_fragment_samples"], 0)
                        if variant == "tiles-deferred":
                            self.assertEqual(details["protocol"], "are.deferred-visibility.v1")
                            self.assertGreater(details["final_shaded_samples"], 0)

    def test_rotation_balances_positions_and_preserves_all_variants(self):
        orders = [order_for_pair(i) for i in range(15)]
        for order in orders:
            self.assertEqual(set(order), set(VARIANTS))
        for variant in VARIANTS:
            positions = [order.index(variant) for order in orders]
            self.assertEqual(sorted(positions), [0]*5 + [1]*5 + [2]*5)

    def test_statistics_report_only_paired_ratios_not_quotients_of_medians(self):
        # Contract-only arithmetic, not benchmark or performance evidence.
        samples = [
            {"ms": {"tiles": a, "batch-first": b, "tiles-deferred": c}}
            for a, b, c in ((3.0, 2.0, 1.0), (9.0, 4.0, 8.0), (2.0, 1.5, 1.25))
        ]
        summary = summarize(samples)
        self.assertEqual(summary["medians_ms"]["tiles"], 3.0)
        self.assertEqual(summary["speedup_paired"]["deferred_vs_scalar"],
                         sorted((3., 9./8., 2./1.25))[1])
        self.assertEqual(summary["faster_pairs"]["deferred_vs_batch"], 2)

    def test_integrity_gate_rejects_missing_or_modified_receipt(self):
        with self.assertRaisesRegex(ValueError, "THREEWAY_RECEIPT_HASH"):
            validate_report({"protocol": "are.deferred.threeway.v1",
                             "sha256": "0"*64})


if __name__ == "__main__":
    unittest.main()
