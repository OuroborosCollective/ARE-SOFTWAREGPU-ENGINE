"""Execute the actual cache benchmark/CLI and reject inconsistent exports."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest

from software_gpu.benchmarks.compare_preparation_cache import (
    ROOT, SCENES, audit, main, measure_case, sources,
)


class TestPreparationCacheBenchmark(unittest.TestCase):
    def test_real_cli_exports_stats_frames_and_auditable_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            main(["--output-dir", folder, "--repeats", "2", "--pixels", "32",
                  "--scenes", "tiny", "small-triangles", "--max-seconds", "0"])
            receipt = json.loads((Path(folder) / "preparation-cache-benchmark.json").read_text())
            self.assertEqual(audit(receipt, root=ROOT)["cases"], 6)
            self.assertEqual(audit(receipt)["draws_including_warmups"], 54)
            self.assertIn("Paired ratio", (Path(folder) / "preparation-cache-report.html").read_text())
            corruptions = (
                lambda r: r.__setitem__("protocol", "unknown"),
                lambda r: r["source_paths_sha256"].__setitem__(next(iter(sources())), "0" * 64),
                lambda r: r["results"][0].__setitem__("byte_identical", False),
                lambda r: r["results"][0]["samples_ms"]["uncached"].__setitem__(0, float("nan")),
                lambda r: r["results"][0]["stats_ms"]["uncached"].__setitem__("median", -1),
                lambda r: r["results"][0]["cache_receipts"]["cache-warm"][0].__setitem__("status", "miss"),
            )
            for corrupt in corruptions:
                changed = copy.deepcopy(receipt)
                corrupt(changed)
                with self.assertRaises(ValueError):
                    audit(changed, root=ROOT)

    def test_bounded_child_completes_and_timeout_preserves_existing_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            command = ["--output-dir", folder, "--repeats", "1", "--pixels", "32",
                       "--scenes", "tiny", "--scenarios", "static"]
            main(command + ["--max-seconds", "30"])
            target = Path(folder) / "preparation-cache-benchmark.json"
            previous = target.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "BUDGET_EXCEEDED"):
                main(command + ["--max-seconds", ".000001"])
            self.assertEqual(target.read_bytes(), previous)
            with self.assertRaisesRegex(RuntimeError, "CHILD_FAILED"):
                main(command + ["--scenes", "procedural5k", "--cache-mib", "1", "--max-seconds", "30"])
            self.assertEqual(target.read_bytes(), previous)

    def test_deadline_rejects_late_case_without_output(self):
        with self.assertRaisesRegex(RuntimeError, "BUDGET_EXCEEDED"):
            measure_case(*SCENES[0], 32, 1, 1, "static", 1 << 20, deadline=time.monotonic() - 1)

    def test_cli_rejects_invalid_limits(self):
        for option, value in (("--pixels", "31"), ("--workers", "17"), ("--repeats", "0"),
                              ("--cache-mib", "0"), ("--max-seconds", "nan"), ("--max-seconds", "inf"),
                              ("--max-seconds", "-1"), ("--scenarios", "wave")):
            with self.subTest(option=option, value=value), self.assertRaises(SystemExit):
                main(["--output-dir", "unused", option, value])


if __name__ == "__main__":
    unittest.main()
