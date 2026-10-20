"""Real C++17 native raster and deterministic time-window single-origin pulse."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from software_gpu.research.native_symbolic import FLAGS, compiler

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"native/raster/single_origin_time_window_test.cpp"

class TestSingleOriginTimeWindow(unittest.TestCase):
    def test_animated_pulse_native_cpp_wolfram_parity_and_15_pairs(self):
        with tempfile.TemporaryDirectory(prefix="are-time-wave-") as directory:
            exe=Path(directory)/("time_wave.exe" if sys.platform=="win32" else "time_wave")
            build=subprocess.run([compiler(),*FLAGS,str(SOURCE),"-o",str(exe)],
                                 capture_output=True,text=True,timeout=120)
            self.assertEqual(build.returncode,0,build.stderr[-7000:])
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=180)
            self.assertEqual(run.returncode,0,run.stderr[-8000:]+run.stdout[-3500:])
            self.assertIn("SINGLE_ORIGIN_TIME_NATIVE_PASS",run.stdout)
            self.assertEqual(run.stdout.count("SINGLE_ORIGIN_TIME_RECEIPT"),4)
            print(run.stdout,flush=True)

if __name__=="__main__":
    unittest.main()
