"""Real cross-platform file-output checks, no graphics hardware required."""
import os
from pathlib import Path
import tempfile
import unittest

from software_gpu.core.output import output_file
from software_gpu.examples.render_3d_scene import main as render_sphere


class TestPortableOutput(unittest.TestCase):
    def test_refuses_directory_traversal(self):
        for filename in ("", ".", "..", "../escape", "..\\escape", "subdir/file"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                output_file(filename)

    def test_respects_real_output_directory(self):
        previous = os.environ.get("ARE_SOFTWAREGPU_OUTPUT_DIR")
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.environ["ARE_SOFTWAREGPU_OUTPUT_DIR"] = directory
                result = Path(output_file("frame.bmp"))
                self.assertEqual(result.parent.resolve(), Path(directory).resolve())
                result.write_bytes(b"BM")
                self.assertEqual(result.read_bytes(), b"BM")
        finally:
            if previous is None:
                os.environ.pop("ARE_SOFTWAREGPU_OUTPUT_DIR", None)
            else:
                os.environ["ARE_SOFTWAREGPU_OUTPUT_DIR"] = previous

    def test_real_cpu_rasterizer_writes_bmp(self):
        previous = os.environ.get("ARE_SOFTWAREGPU_OUTPUT_DIR")
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.environ["ARE_SOFTWAREGPU_OUTPUT_DIR"] = directory
                render_sphere()
                image = Path(directory, "software_gpu_sphere.bmp")
                self.assertTrue(image.is_file())
                self.assertGreater(image.stat().st_size, 54)
                self.assertEqual(image.read_bytes()[:2], b"BM")
        finally:
            if previous is None:
                os.environ.pop("ARE_SOFTWAREGPU_OUTPUT_DIR", None)
            else:
                os.environ["ARE_SOFTWAREGPU_OUTPUT_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
