"""Real C++17 native-raster Doppler-only vs no effect vs SpherePop Doppler.

Wolfram algebra is an independent oracle; timings are 15 AB/BA CPU pairs.
No mocks, no production activation, no whole-game speedup claim.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from software_gpu.research.native_symbolic import compiler, FLAGS

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "native/raster/doppler_only_native_test.cpp"

class TestWolframCppDopplerOnly(unittest.TestCase):
    def test_real_native_raster_doppler_only_three_way(self):
        with tempfile.TemporaryDirectory(prefix="are-doppler-only-") as temp:
            exe = Path(temp) / ("doppler_only.exe" if sys.platform=="win32" else "doppler_only")
            c = subprocess.run([compiler(), *FLAGS, str(SOURCE), "-o", str(exe)],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(c.returncode, 0, c.stderr[-8000:])
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=90)
            self.assertEqual(r.returncode, 0, r.stderr[-6000:]+r.stdout[-3000:])
            self.assertIn("DOPPLER_ONLY_REAL_RASTER_TEST_PASS", r.stdout)
            self.assertEqual(r.stdout.count("DOPPLER_ONLY_FRAME_RECEIPT"), 2)
            print(r.stdout,flush=True)

if __name__ == "__main__":
    unittest.main()
