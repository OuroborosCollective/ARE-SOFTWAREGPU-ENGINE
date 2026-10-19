"""Compile and execute actual native C++17 SpherePop object-mask regressions.

Real core raster, original contracts and exact platform compiler; no mocks.
"""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from software_gpu.research.native_symbolic import FLAGS, compiler

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    ROOT / "native/raster/spherepop_object_mask_native_test.cpp",
    ROOT / "native/raster/spherepop_object_mask_contract_test.cpp",
)
SOURCES = (
    ROOT / "native/raster/spherepop_object_mask.hpp",
    ROOT / "native/raster/spherepop_doppler_profile.hpp",
    ROOT / "native/raster/core.hpp",
    ROOT / "native/symbolic/core.hpp",
)


class TestSpherePopObjectMaskNative(unittest.TestCase):
    def test_real_native_draw_and_fail_closed_object_mask(self):
        executable_compiler = compiler()
        with tempfile.TemporaryDirectory(prefix="are-spherepop-mask-") as tmp:
            for index, source in enumerate(FILES):
                with self.subTest(source=source.name):
                    output = Path(tmp) / ("mask_%d.exe" % index if sys.platform == "win32" else "mask_%d" % index)
                    build = subprocess.run([executable_compiler, *FLAGS,
                        str(source), "-o", str(output)],
                        text=True, capture_output=True, timeout=120)
                    self.assertEqual(build.returncode, 0, build.stderr[-6000:])
                    run = subprocess.run([str(output)], text=True,
                        capture_output=True, timeout=30)
                    self.assertEqual(run.returncode, 0, run.stderr[-6000:])
                    self.assertIn("PASS ", run.stdout)
        for source in (*FILES, *SOURCES):
            self.assertEqual(len(hashlib.sha256(source.read_bytes()).hexdigest()), 64)


if __name__ == "__main__":
    unittest.main()
