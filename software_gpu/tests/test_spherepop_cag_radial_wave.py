"""Real C++17 CAG/SpherePop/Doppler wavefront compile-and-execute gate."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from software_gpu.research.native_symbolic import FLAGS, compiler

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "native/raster/spherepop_cag_radial_wave_test.cpp"

class TestCagSpherePopRadialWave(unittest.TestCase):
    def test_native_raster_radial_wave_completion_and_replay(self):
        cxx = compiler()
        with tempfile.TemporaryDirectory(prefix="are-cag-spherepop-wave-") as tmp:
            exe = Path(tmp) / ("wave.exe" if sys.platform == "win32" else "wave")
            compiled = subprocess.run([cxx, *FLAGS, str(SOURCE), "-o", str(exe)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stderr[-6000:])
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=25)
            self.assertEqual(run.returncode, 0, run.stderr[-6000:])
            self.assertIn("PASS real native CAG->SpherePop radial Doppler wavefront", run.stdout)

if __name__ == "__main__":
    unittest.main()
