"""Compile C++17 optional profile against the real native raster; no mock raster."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from software_gpu.research.native_symbolic import FLAGS, compiler

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "native/raster/spherepop_doppler_test.cpp"
HEADER = ROOT / "native/raster/spherepop_doppler_profile.hpp"
RASTER = ROOT / "native/raster/core.hpp"
SYMBOLIC = ROOT / "native/symbolic/core.hpp"


class TestSpherePopCagDoppler(unittest.TestCase):
    def test_real_raster_doppler_depth_replay_and_negative_fp_cases(self):
        cxx = compiler()  # Missing native compiler fails the gate, never skips.
        with tempfile.TemporaryDirectory(prefix="are-spherepop-doppler-") as tmp:
            output = Path(tmp) / ("profile.exe" if sys.platform == "win32" else "profile")
            command = [cxx, *FLAGS, str(SOURCE), "-o", str(output)]
            built = subprocess.run(command, text=True, capture_output=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stderr[-6000:])
            run = subprocess.run([str(output)], text=True, capture_output=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr[-6000:])
            self.assertIn("PASS native real raster + Doppler", run.stdout)
            for file in (SOURCE, HEADER, RASTER, SYMBOLIC):
                self.assertEqual(len(hashlib.sha256(file.read_bytes()).hexdigest()), 64)


if __name__ == "__main__":
    unittest.main()
