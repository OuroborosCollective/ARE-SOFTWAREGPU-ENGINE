"""Release requires actual selected targets and independent renderer vectors."""
import hashlib
import json
import os
import subprocess
import unittest
from unittest.mock import patch

import numpy as np

from software_gpu.research.pre_delivery_scan import scan_before_delivery
from software_gpu.tests.test_symbolic_wave import NODE, fixture, inputs, oracle


def cases():
    return [{"inputs": (data := inputs(fixture(), seed)), "expected": {"edge": oracle(data)}}
            for seed in range(2)]


class TestPreDeliveryScan(unittest.TestCase):
    def test_python_delivery_receipt_binds_the_executed_source(self):
        delivered = scan_before_delivery(fixture(), cases(), ["python"])
        self.assertEqual(delivered["status"], "PASS")
        receipt = delivered["receipt"]
        self.assertEqual(receipt["oracle_cases"], 2)
        self.assertEqual(len(receipt["checks"]), 2)
        self.assertEqual(receipt["source_sha256"]["python"],
                         hashlib.sha256(delivered["sources"]["python"].encode()).hexdigest())
        self.assertEqual(receipt["truth_layers"]["numerical"], "passed-supplied-oracles")
        self.assertEqual(receipt["truth_layers"]["external_world"], "unknown")

    def test_fail_closed_bad_or_missing_oracles(self):
        for value in ([], [None], [{"inputs": {}, "expected": {}}], cases()*17):
            with self.assertRaises(ValueError): scan_before_delivery(fixture(), value, ["python"])
        for value in (np.zeros((1,), np.float32), np.zeros((2,2,3), np.float64),
                      np.full((2,2,3), np.nan, np.float32), [0]):
            bad = cases(); bad[0]["expected"]["edge"] = value
            with self.assertRaisesRegex(ValueError, "ORACLE_TYPE"):
                scan_before_delivery(fixture(), bad, ["python"])
        bad = cases(); bad[0]["expected"]["edge"] = -bad[0]["expected"]["edge"]
        with self.assertRaisesRegex(ValueError, "ORACLE_MISMATCH"):
            scan_before_delivery(fixture(), bad, ["python"])
        bad = cases(); bad[0]["inputs"]["px"] = np.zeros((1,),np.float32)
        with self.assertRaisesRegex(ValueError, "INPUT_TYPE"):
            scan_before_delivery(fixture(), bad, ["python"])

    def test_language_budgets_and_missing_requested_runtime_block_delivery(self):
        for languages in ([], ["rust"], ["python", "python"], "python", [None]):
            with self.assertRaisesRegex(ValueError, "LANGUAGES"):
                scan_before_delivery(fixture(), cases(), languages)
        for seconds in (0, -1, 31, float("inf"), float("nan"), True):
            with self.assertRaisesRegex(ValueError, "BUDGET"):
                scan_before_delivery(fixture(), cases(), ["python"], seconds=seconds)
        with patch.dict(os.environ, {"CODEX_PRIMARY_RUNTIME_NODE": ""}), patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "NODE_REQUIRED"):
                scan_before_delivery(fixture(), cases())

    @unittest.skipUnless(NODE, "Node.js needed for cross-language release proof")
    def test_actual_cross_language_delivery_and_javascript_only(self):
        result = scan_before_delivery(fixture(), cases())
        self.assertEqual(set(result["sources"]), {"python", "javascript"})
        self.assertEqual(len(result["receipt"]["checks"]), 4)
        self.assertEqual(scan_before_delivery(fixture(), cases(), ["javascript"])["status"], "PASS")
        bad = cases(); bad[0]["expected"]["edge"] = -bad[0]["expected"]["edge"]
        with self.assertRaisesRegex(ValueError, "ORACLE_MISMATCH"):
            scan_before_delivery(fixture(), bad, ["javascript"])

    def test_target_failure_timeout_or_wrong_output_blocks_delivery(self):
        # Fault injection tests delivery gates, not target numerical performance.
        with patch.dict(os.environ, {"CODEX_PRIMARY_RUNTIME_NODE": "node"}):
            for error in (OSError("missing"), subprocess.TimeoutExpired("node",10),
                          subprocess.CalledProcessError(1,"node")):
                with patch("subprocess.run", side_effect=error):
                    with self.assertRaisesRegex(ValueError, "TARGET_FAILED"):
                        scan_before_delivery(fixture(), cases(), ["javascript"])
            for stdout in ("bad-json", "[]", json.dumps({"wrong": []}), json.dumps({"edge": []})):
                with patch("subprocess.run", return_value=subprocess.CompletedProcess([],0,stdout,"")):
                    with self.assertRaisesRegex(ValueError, "TARGET_FAILED|ORACLE_MISMATCH"):
                        scan_before_delivery(fixture(), cases(), ["javascript"])
