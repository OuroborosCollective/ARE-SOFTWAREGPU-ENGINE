"""Real native C++17 single-origin impact against chained wave; 15 CPU pairs."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from software_gpu.research.native_symbolic import FLAGS, compiler

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"native/raster/single_origin_impact_test.cpp"

class TestSingleOriginImpact(unittest.TestCase):
    def test_native_raster_single_origin_impact_once_and_perf(self):
        with tempfile.TemporaryDirectory(prefix="are-single-impact-") as temp:
            exe=Path(temp)/("single_impact.exe" if sys.platform=="win32" else "single_impact")
            build=subprocess.run([compiler(),*FLAGS,str(SOURCE),"-o",str(exe)],
                text=True,capture_output=True,timeout=120)
            self.assertEqual(build.returncode,0,build.stderr[-9000:])
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stderr[-9000:]+result.stdout[-5000:])
            self.assertIn("SINGLE_ORIGIN_NATIVE_PASS",result.stdout)
            self.assertEqual(result.stdout.count("SINGLE_ORIGIN_IMPACT_RECEIPT"),2)
            print(result.stdout,flush=True)

if __name__=="__main__":unittest.main()
