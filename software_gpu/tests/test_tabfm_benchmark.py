"""Regression controls on the committed measured native raster benchmark receipt."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from software_gpu.research import tabfm_benchmark as analysis

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "evidence/native-raster-surface-plan-metrics-v1.json"


class TestTabFMOfflineResearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real = json.loads(RECEIPT.read_text(encoding="utf-8"))

    def changed_receipt(self, changed):
        folder = tempfile.TemporaryDirectory(prefix="tabfm-negative-")
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "modified-real-receipt.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        return path

    def test_only_genuine_recorded_samples_and_pre_runtime_features(self):
        loaded = analysis.load_real_receipt(RECEIPT)
        self.assertEqual(len(loaded["scenes"]), 5)
        self.assertEqual(len(loaded["plans"]), 8)
        self.assertEqual(len(loaded["rows"]), 40)
        self.assertEqual(loaded["source_sha256"],
                         hashlib.sha256(RECEIPT.read_bytes()).hexdigest())
        self.assertEqual(analysis.FEATURES, ("triangles", "pixels", "workers", "plan"))
        self.assertTrue(all(x["median_ms"] > 0 for x in loaded["rows"]))

    def test_real_leave_one_scene_out_is_repeatable_and_auditable(self):
        first = analysis.evaluate(RECEIPT)
        second = analysis.evaluate(RECEIPT)
        self.assertEqual(first, second)
        self.assertEqual(first["mode"], "baseline")
        self.assertFalse(first["weight_download_requested"])
        self.assertIsNone(first["tabfm_upstream_sha"])
        self.assertEqual(first["n_rows"], 40)
        self.assertEqual({f["held_out_scene"] for f in first["folds"]},
                         set(analysis.load_real_receipt(RECEIPT)["scenes"]))
        self.assertEqual(sum(f["metrics"]["n"] for f in first["folds"]), 40)
        for fold in first["folds"]:
            self.assertNotIn(fold["held_out_scene"], fold["training_scenes"])
            self.assertEqual(fold["n_training"], 32)
            self.assertEqual(fold["metrics"]["n"], 8)
        digest = first.pop("report_sha256")
        self.assertEqual(digest, analysis._sha(analysis._canonical(first)))

    def test_actual_evidence_tampering_denied(self):
        for mutation, message in (
            (lambda r: r["results"][0].update(byte_identical=False),
             "RENDER_PARITY_REQUIRED"),
            (lambda r: r["results"][0].update(gpu_parity_established=True),
             "GPU_PARITY_CLAIM_REJECTED"),
            (lambda r: r["results"][0]["stats_ms"]["tiles"].update(median=1e6),
             "MEDIAN_MISMATCH"),
            (lambda r: r["results"][0]["samples_ms"]["tiles"].__setitem__(0, 0),
             "NON_POSITIVE_OR_NONFINITE"),
            (lambda r: r["results"][0]["stats_ms"].pop("tiles"),
             "PLAN_SAMPLES_MISMATCH"),
            (lambda r: r["results"][0].update(scene=r["results"][1]["scene"]),
             "SCENE_DUPLICATE_OR_MISSING"),
        ):
            with self.subTest(failure=message):
                mutated = copy.deepcopy(self.real)
                mutation(mutated)
                with self.assertRaisesRegex(ValueError, message):
                    analysis.load_real_receipt(self.changed_receipt(mutated))

    def test_weight_license_blocks_before_any_io_or_optional_import(self):
        nonexistent = Path("/tabfm-intentionally-absent/receipt.json")
        with self.assertRaisesRegex(PermissionError, "NOT_AUTHORIZED"):
            analysis.evaluate(nonexistent, "tabfm", confirm_research_rights=False)
        with mock.patch.dict(os.environ, {"ARE_TABFM_NONCOMMERCIAL_RESEARCH": "0"}):
            with self.assertRaisesRegex(PermissionError, "NOT_AUTHORIZED"):
                analysis.evaluate(nonexistent, "tabfm", confirm_research_rights=True)

    def test_cli_produces_a_real_receipt_without_model_weights(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "analysis.json"
            analysis.main(["--input", str(RECEIPT), "--output", str(path)])
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report, analysis.evaluate(RECEIPT))
            self.assertEqual(report["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
