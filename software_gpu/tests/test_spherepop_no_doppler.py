"""Run true C++17 SpherePop wave ablation without Doppler; retain measured stdout."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from software_gpu.research.native_symbolic import FLAGS, compiler

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"native/raster/spherepop_no_doppler_test.cpp"

class TestSpherePopNoDoppler(unittest.TestCase):
    def test_no_doppler_is_one_shot_and_cpu_pair_benchmark(self):
        with tempfile.TemporaryDirectory(prefix="are-wave-no-doppler-") as directory:
            exe=Path(directory)/("no_doppler.exe" if sys.platform=="win32" else "no_doppler")
            p=subprocess.run([compiler(),*FLAGS,str(SOURCE),"-o",str(exe)],
                             capture_output=True,text=True,timeout=120)
            self.assertEqual(p.returncode,0,p.stderr[-6000:])
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=90)
            self.assertEqual(run.returncode,0,run.stderr[-6000:]+run.stdout[-1000:])
            self.assertIn("SPHEREPOP_NO_DOPPLER_RESULT",run.stdout)
            print(run.stdout.strip(),flush=True)

if __name__=="__main__":
    unittest.main()
