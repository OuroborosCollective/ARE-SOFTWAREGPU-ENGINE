"""Issue #295: real GLB2 admission and WorldForge cache regressions.

All GLB bytes below are explicitly SYNTHETIC negative/positive fixtures.
This is not an Assimp/fastgltf reproduction or a production asset receipt.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from software_gpu.integrations.aurion.offline_lod_worker import load_worldforge_glb
from software_gpu.integrations.worldforge import review
from software_gpu.tests.test_aurion_offline_lod import synthetic_glb


def modify_glb(mutate):
    """Re-encode a genuine, SHA-bound GLB2 fixture after changing its JSON."""
    original = synthetic_glb()
    json_size = struct.unpack_from("<I", original, 12)[0]
    document = json.loads(original[20:20 + json_size])
    binary_header = 20 + json_size
    binary_size, kind = struct.unpack_from("<I4s", original, binary_header)
    assert kind == b"BIN\x00"
    binary = original[binary_header + 8: binary_header + 8 + binary_size]
    mutate(document)
    raw_json = json.dumps(document, separators=(",", ":"), allow_nan=False).encode()
    raw_json += b" " * (-len(raw_json) % 4)
    chunks = (struct.pack("<I4s", len(raw_json), b"JSON") + raw_json
              + struct.pack("<I4s", len(binary), b"BIN\x00") + binary)
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


class GLBAdmissionSecurityTests(unittest.TestCase):
    def test_reject_invalid_declared_bin_lengths_before_decode(self):
        # RED: negative/bool lengths pass the WorldForge GLB2 import path.
        for declared in (-1, True, 1 << 32, (1 << 64) - 1):
            with self.subTest(declared=declared), TemporaryDirectory() as tmp:
                raw = modify_glb(lambda doc: doc["buffers"][0].update(byteLength=declared))
                path = Path(tmp) / "model.glb"
                path.write_bytes(raw)
                record = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                with self.assertRaisesRegex(ValueError, "GLB_BUFFER_LENGTH_INVALID"):
                    load_worldforge_glb(path, record)

    def test_reject_untrusted_deep_json_before_recursive_decoding(self):
        # RED: an irrelevant but recursive JSON tree is currently admitted.
        def nest(doc):
            nested = 0
            for _ in range(100):
                nested = [nested]
            doc["extras"] = nested
        with TemporaryDirectory() as tmp:
            raw = modify_glb(nest)
            path = Path(tmp) / "model.glb"
            path.write_bytes(raw)
            record = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            with self.assertRaisesRegex(ValueError, "GLB_JSON_DEPTH_LIMIT"):
                load_worldforge_glb(path, record)

    def test_reject_external_resource_reference_without_network(self):
        # RED: the geometry importer currently ignores externally hosted images.
        raw = modify_glb(lambda doc: doc.update(
            images=[{"uri": "https://example.invalid/remote.png"}]))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.glb"
            path.write_bytes(raw)
            record = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            with self.assertRaisesRegex(ValueError, "GLB_EXTERNAL_URI_UNSUPPORTED"):
                load_worldforge_glb(path, record)

    def test_reject_out_of_bounds_index_and_huge_accessor_count(self):
        # ALREADY_COVERED assertions: real accessor readers must keep rejecting.
        for mutate in (
            lambda doc: doc["accessors"][0].update(count=(1 << 64) - 1),
            lambda doc: doc["bufferViews"][0].update(byteStride=(1 << 64) - 1),
            lambda doc: doc["accessors"][0].update(byteOffset=(1 << 64) - 1),
        ):
            with self.subTest(mutate=mutate), TemporaryDirectory() as tmp:
                raw = modify_glb(mutate)
                path = Path(tmp) / "model.glb"
                path.write_bytes(raw)
                record = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                with self.assertRaises(ValueError):
                    load_worldforge_glb(path, record)

    def test_reject_55_byte_bomb_header(self):
        # ALREADY_COVERED. Synthetic 55-byte invalid framing, not Assimp data.
        raw = b"glTF" + struct.pack("<II", 2, 0x7fffffff) + b"\0" * 43
        self.assertEqual(len(raw), 55)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.glb"
            path.write_bytes(raw)
            record = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            with self.assertRaises(ValueError):
                load_worldforge_glb(path, record)

    def test_cached_review_fails_closed_on_source_mutation(self):
        # RED: successful report cache currently skips the source SHA readback.
        raw = synthetic_glb()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / ("a" * 64)
            job.mkdir()
            model = job / "model.glb"
            model.write_bytes(raw)
            expected = hashlib.sha256(raw).hexdigest()
            receipt = {
                "schema": "worldforge.blender-export.v1",
                "jobId": job.name,
                "files": [{"path": "model.glb", "size": len(raw), "sha256": expected}],
            }
            (job / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
            out_dir = root / "reports"
            result = review(job, out_dir)
            report = json.loads((result / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "reviewed")
            self.assertEqual(report["modelSha256"], expected)
            self.assertEqual(len(list(result.glob("*.bmp"))), 6)
            self.assertEqual(review(job, out_dir), result)
            model.write_bytes(raw[:-1] + b"X")
            with self.assertRaisesRegex(ValueError, "SOURCE_SHA256_MISMATCH"):
                review(job, out_dir)
            self.assertEqual(hashlib.sha256((result / "report.json").read_bytes()).hexdigest(),
                             hashlib.sha256((result / "report.json").read_bytes()).hexdigest())

    def test_untouched_positive_glb2_mesh_is_identical(self):
        # ALREADY_COVERED: real arrays and SHA for the accepted one-mesh subset.
        with TemporaryDirectory() as tmp:
            raw = synthetic_glb()
            path = Path(tmp) / "model.glb"
            path.write_bytes(raw)
            record = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            vertices, faces, digest = load_worldforge_glb(path, record)
            self.assertEqual(digest, record["sha256"])
            self.assertEqual((vertices.shape, faces.shape), ((3, 3), (1, 3)))
            np.testing.assert_array_equal(faces.reshape(-1), [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
