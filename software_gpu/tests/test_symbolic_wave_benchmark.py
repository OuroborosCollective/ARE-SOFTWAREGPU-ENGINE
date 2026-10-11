"""Benchmark receipt integration and bounded CLI, with the real kernels."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from software_gpu.benchmarks.compare_symbolic_waves import main


class TestSymbolicWaveBenchmark(unittest.TestCase):
    def test_actual_receipt_parity_statistics_and_source_binding(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/"benchmark.json"
            argv = ["bench", "--root", str(root), "--output", str(target), "--repeats", "15"]
            with patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                main()
            receipt = json.loads(target.read_text())
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["measured_evaluations"], 675)
        self.assertEqual(receipt["git_head"], receipt["git_head_after"])
        self.assertEqual(receipt["source_sha256"], receipt["source_after_sha256"])
        self.assertEqual(receipt["benchmark_script_sha256"],
                         receipt["source_sha256"]["software_gpu/benchmarks/compare_symbolic_waves.py"])
        self.assertEqual(len(receipt["cases"]), 15)
        for case in receipt["cases"]:
            self.assertEqual(case["parity"], "byte-identical")
            self.assertEqual(len(case["frame_sha256"]), 15)
            for mode, stats in case["stats_ms"].items():
                self.assertEqual(stats["n"], 15)
                self.assertEqual(len(case["raw_ms"][mode]), 15)
                self.assertGreaterEqual(stats["iqr"], 0)
                self.assertGreaterEqual(stats["mad"], 0)
            if case["scenario"] == "static":
                self.assertTrue(all(not r["executed_nodes"] for r in case["receipts"]))
            if case["family"] == "rooms-32" and case["scenario"] == "one-input":
                self.assertTrue(all(len(r["executed_nodes"]) == 6 for r in case["receipts"]))

    def test_cli_rejects_unbounded_repeat_values(self):
        for repeats in ("0", "14", "31"):
            with patch("sys.argv", ["bench", "--root", ".", "--output", "unused", "--repeats", repeats]):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    main()
            self.assertEqual(caught.exception.code, 2)
