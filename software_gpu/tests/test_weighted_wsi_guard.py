"""Actual source-bound WSI verifier negative controls (no driver simulation)."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from software_gpu.drivers.verify_weighted_wsi import sha, verify

REPO = Path(__file__).resolve().parents[2]


class TestWeightedWsiVerifierGuard(unittest.TestCase):
    def test_real_bytes_are_the_sha_authority(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "frame.rgba"
            payload = bytes.fromhex("0001027f80feff")
            file.write_bytes(payload)
            self.assertEqual(sha(file), hashlib.sha256(payload).hexdigest())
            file.write_bytes(payload + b"\0")
            self.assertNotEqual(sha(file), hashlib.sha256(payload).hexdigest())

    def test_nonrevision_cannot_create_a_benchmark_directory(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "untrusted"
            with self.assertRaisesRegex(RuntimeError, "ARE_WSI_SOURCE_REVISION_MISMATCH"):
                verify(output, "no-revision", Path(td) / "missing.xml",
                       Path(td) / "missing-vulkan")
            self.assertFalse(output.exists())

    def test_forged_full_sha_cannot_create_an_evidence_directory(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "untrusted"
            actual = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                             cwd=REPO, text=True).strip()
            wrong = ("0" if actual[0] != "0" else "1") + actual[1:]
            with self.assertRaisesRegex(RuntimeError, "ARE_WSI_SOURCE_REVISION_MISMATCH"):
                verify(output, wrong, Path(td) / "missing.xml", Path(td) / "missing")
            self.assertFalse(output.exists())

    def test_existing_output_cannot_be_overwritten_or_relabelled(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "existing"
            output.mkdir()
            sentinel = output / "original-receipt.json"
            sentinel.write_bytes(b'{"provenance":"already-saved"}')
            actual = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                             cwd=REPO, text=True).strip()
            with self.assertRaisesRegex(ValueError, "ARE_WSI_REQUIRE_EMPTY_OUTPUT"):
                verify(output, actual, Path(td) / "missing.xml", Path(td) / "missing")
            self.assertEqual(sentinel.read_bytes(), b'{"provenance":"already-saved"}')


if __name__ == "__main__":
    unittest.main()
