"""Compile and run real C++17 raster + SpherePop Doppler factor reuse A/B.

CI emits the 15-pair timings and bit-identical frame/history evidence;
new mode stays opt-in pending sufficient benchmark evidence.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from software_gpu.research.native_symbolic import FLAGS, compiler

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"native/raster/spherepop_factor_reuse_test.cpp"

class TestSpherePopFactorReuse(unittest.TestCase):
    def test_true_raster_factor_reuse_equivalence_and_15_pairs(self):
        with tempfile.TemporaryDirectory(prefix="are-factor-reuse-") as directory:
            exe=Path(directory)/("factor_reuse.exe" if sys.platform=="win32" else "factor_reuse")
            build=subprocess.run([compiler(),*FLAGS,str(SOURCE),"-o",str(exe)],
                                 capture_output=True,text=True,timeout=120)
            self.assertEqual(build.returncode,0,build.stderr[-8000:])
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=120)
            self.assertEqual(run.returncode,0,run.stderr[-8000:]+run.stdout[-3500:])
            self.assertIn("SPHEREPOP_FACTOR_REUSE_NATIVE_PASS",run.stdout)
            self.assertEqual(run.stdout.count("SPHEREPOP_FACTOR_REUSE_RECEIPT"),2)
            print(run.stdout,flush=True)

if __name__=="__main__":
    unittest.main()
