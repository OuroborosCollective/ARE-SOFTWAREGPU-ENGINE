"""Native C++17 direct Doppler-only vs SpherePop+ Doppler real raster regression."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from software_gpu.research.native_symbolic import FLAGS, compiler
ROOT=Path(__file__).resolve().parents[2]

class TestWolframDopplerOnly(unittest.TestCase):
    def test_real_native_raster_doppler_only_three_way_15_pairs(self):
        with tempfile.TemporaryDirectory(prefix="are-doppler-only-") as tmp:
            exe=Path(tmp)/("doppler.exe" if sys.platform=="win32" else "doppler")
            built=subprocess.run([compiler(),*FLAGS,str(ROOT/"native/raster/doppler_only_native_test.cpp"),"-o",str(exe)],
                                 text=True,capture_output=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr[-6000:])
            run=subprocess.run([str(exe)],text=True,capture_output=True,timeout=120)
            self.assertEqual(run.returncode,0,run.stderr[-6000:]+run.stdout[-1000:])
            self.assertEqual(run.stdout.count("DOPPLER_ONLY_FRAME_RECEIPT"),2)
            self.assertIn("DOPPLER_ONLY_REAL_RASTER_TEST_PASS",run.stdout)
            print(run.stdout,flush=True)

if __name__=="__main__":
    unittest.main()
