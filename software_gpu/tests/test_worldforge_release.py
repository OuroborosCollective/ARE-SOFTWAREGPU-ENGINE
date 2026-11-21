import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from software_gpu._version import build_version
from software_gpu.integrations.worldforge import review
from software_gpu.tests.test_aurion_offline_lod import synthetic_glb


class WorldForgeTests(unittest.TestCase):
    def test_real_geometry_review_and_source_integrity(self):
        data = synthetic_glb()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / ("a" * 64)
            job.mkdir()
            (job / "model.glb").write_bytes(data)
            source = hashlib.sha256(data).hexdigest()
            record = {"schema": "worldforge.blender-export.v1", "jobId": job.name,
                      "files": [{"path": "model.glb", "size": len(data), "sha256": source}]}
            (job / "receipt.json").write_text(json.dumps(record))
            output = review(job, root / "out")
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(report["status"], "reviewed")
            self.assertEqual(len(list(output.glob("*.bmp"))), 6)
            self.assertEqual(review(job, root / "out"), output)
            self.assertEqual(report["levels"][0]["views"][0]["silhouetteIoU"], 1)
            (job / "model.glb").write_bytes(data[:-1] + b"X")
            with self.assertRaisesRegex(ValueError, "SOURCE_SHA256_MISMATCH"):
                review(job, root / "fresh")

    def test_source_distribution_preserves_published_version(self):
        from unittest.mock import patch
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "PKG-INFO").write_text("Name: ouroboroscollective-softwaregpu\nVersion: 1.2.314\n")
            with patch.dict("os.environ", {"ARE_BUILD_TAG": ""}):
                self.assertEqual(build_version(root), "1.2.314")
            with patch.dict("os.environ", {"ARE_BUILD_TAG": "v1.2.315"}):
                self.assertEqual(build_version(root), "1.2.315")
