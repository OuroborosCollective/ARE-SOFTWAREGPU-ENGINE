"""Compile and time real native C++17 raster + Wolfram Doppler-only ablation.

No mocks, no arbitrary performance threshold, raw 15-pair receipts emitted in CI.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from software_gpu.research.native_symbolic import FLAGS, compiler

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"native/raster/doppler_only_native_test.cpp"

class TestDopplerOnlyWolframNative(unittest.TestCase):
    def test_wolfram_oracle_and_real_native_three_way_frames(self):
        with tempfile.TemporaryDirectory(prefix="are-doppler-only-") as directory:
            exe=Path(directory)/("doppler_only.exe" if sys.platform=="win32" else "doppler_only")
            cmd=[compiler(),*FLAGS,str(SOURCE),"-o",str(exe)]
            build=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
            self.assertEqual(build.returncode,0,build.stderr[-6000:])
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=90)
            self.assertEqual(run.returncode,0,run.stderr[-6000:]+run.stdout[-1500:])
            self.assertIn("DOPPLER_ONLY_REAL_RASTER_TEST_PASS",run.stdout)
            self.assertEqual(run.stdout.count("DOPPLER_ONLY_FRAME_RECEIPT"),2)
            for line in run.stdout.splitlines():
                if line.startswith("DOPPLER_ONLY_FRAME_RECEIPT"):
                    print(line,flush=True)

if __name__=="__main__":
    unittest.main()
