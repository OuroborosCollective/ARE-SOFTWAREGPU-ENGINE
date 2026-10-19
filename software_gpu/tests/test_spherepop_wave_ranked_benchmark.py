"""Measured CPU-only A/B acceptance: real ARE raster, native SpherePop wave.

No mocks or hard-coded times. Covers both eligible 32/64 pixel projections,
15 alternating draws per mode, RGB/depth parity and per-object wave replay.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform.startswith("linux"), "canonical Linux benchmark runner; Windows core wave regressions remain active")
class TestSpherePopWaveRankedBenchmark(unittest.TestCase):
    def test_ranked_cpu_waves_have_real_replay_and_paired_timings(self):
        with tempfile.TemporaryDirectory(prefix="are-wave-ranking-ci-") as tmp:
            path=Path(tmp)/"report.json"
            command=[sys.executable,"-m","software_gpu.benchmarks.compare_spherepop_wave_frames",
                     "--output",str(path),"--pixels","32","64",
                     "--repeats","15","--max-seconds","420"]
            run=subprocess.run(command,text=True,capture_output=True,timeout=460)
            self.assertEqual(run.returncode,0,run.stderr[-6000:]+run.stdout[-2000:])
            report=json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["protocol"],"are.spherepop-wave-ranked-benchmark.v1")
            self.assertEqual(len(report["rows"]),4)
            self.assertTrue(report["no_physical_gpu_comparison"])
            for case in report["rows"]:
                self.assertEqual(case["repeats"],15)
                self.assertEqual(case["wave_metrics"]["finalized"],case["pixels"]**2)
                self.assertGreater(case["wave_metrics"]["refused"],0)
                self.assertNotEqual(case["reference"]["rgba_sha256"],case["effect"]["rgba_sha256"])
                self.assertEqual(case["reference"]["depth_sha256"],case["effect"]["depth_sha256"])
                for mode in ("tiles","batch-first","native-cpp"):
                    timings=case["modes"][mode]["raw_ms"]
                    self.assertEqual(len(timings["off"]),15)
                    self.assertEqual(len(timings["on"]),15)
                    self.assertGreater(case["ranking_with_wave"][mode]["median"],0)
            print("SPHEREPOP_WAVE_BENCHMARK_RECEIPT_START")
            print(json.dumps({"head":report["head_sha"],"rows":[{
                "scene":r["scene"],"pixels":r["pixels"],
                "effect_cost_x":{m:r["modes"][m]["effect_cost_ratio_paired"]["median"]
                                 for m in ("tiles","batch-first","native-cpp")},
                "wave_ranking_x":{m:r["ranking_with_wave"][m]["median"]
                                  for m in ("tiles","batch-first","native-cpp")},
                "baseline_ranking_x":{m:r["ranking_without_wave"][m]["median"]
                                      for m in ("tiles","batch-first","native-cpp")}} for r in report["rows"]]},
                sort_keys=True))
            print("SPHEREPOP_WAVE_BENCHMARK_RECEIPT_END")


if __name__=="__main__":
    unittest.main()
