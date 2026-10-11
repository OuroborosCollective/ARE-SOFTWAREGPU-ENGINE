"""PassMark V11 integrity and negative controls."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

script = Path(__file__).resolve().parents[2] / "tools" / "passmark_v11.py"
spec = importlib.util.spec_from_file_location("passmark_v11",script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class TestPassMarkV11(unittest.TestCase):
    def test_architecture_pins(self):
        self.assertEqual(set(mod.ARCHIVES),{"x86_64","aarch64","armv7l"})
        self.assertEqual(len({v[1] for v in mod.ARCHIVES.values()}),3)
        self.assertEqual({v[3] for v in mod.ARCHIVES.values()},{40,62,183})
        for v in mod.ARCHIVES.values():
            self.assertEqual(len(v[1]),64)
            self.assertEqual(len(v[2]),64)
    def test_missing_archive_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,"PINNED_ARCHIVE_SHA256_MISMATCH"):
                mod.audit(Path(d)/"no.zip","x86_64")
    def test_corrupt_archive_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.zip"
            p.write_bytes(b"invalid")
            with self.assertRaisesRegex(ValueError,"PINNED_ARCHIVE_SHA256_MISMATCH"):
                mod.audit(p,"x86_64")
    def test_modified_archive_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"modified.zip"
            with ZipFile(p,"w") as z:
                z.writestr("PerformanceTest/PerformanceTest_Linux_x86-64",b"\x7fELFbad")
            with self.assertRaisesRegex(ValueError,"PINNED_ARCHIVE_SHA256_MISMATCH"):
                mod.audit(p,"x86_64")
    def test_gpu_profile_forbidden(self):
        with self.assertRaises(SystemExit) as err:
            mod.main(["run","--archive","none.zip","--output-dir","out","--profile","gpu"])
        self.assertEqual(err.exception.code,2)
if __name__=="__main__":
    unittest.main()
