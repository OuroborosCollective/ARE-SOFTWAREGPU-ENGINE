"""Issue #294: codec preflight and numeric admission (synthetic negative fixtures)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from software_gpu.benchmarks.asset_codec_comparison import (
    inspect_glb_container, metadata_signature, quality_metrics,
    paired_statistics, geometry_error,
)


def make_glb(document=None, binary=b'\x00\x00\x00\x00'):
    doc = document or {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4}],
                       "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
                       "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}],
                       "materials": [{"doubleSided": True}]}
    raw = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    raw += b" " * (-len(raw) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(raw) + 8 + len(binary))
            + struct.pack("<I4s", len(raw), b"JSON") + raw
            + struct.pack("<I4s", len(binary), b"BIN\x00") + binary)


class CodecAdmissionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "sample.glb"

    def inspect(self, content=None):
        data = make_glb() if content is None else content
        self.path.write_bytes(data)
        return inspect_glb_container(self.path, hashlib.sha256(data).hexdigest(), len(data))

    def test_real_glb_container_minimum_and_hash(self):
        info = self.inspect()
        self.assertEqual(info["document"]["asset"]["version"], "2.0")
        self.assertEqual(info["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(info["bytes"], self.path.stat().st_size)

    def test_bad_sha_or_wrong_length_is_rejected_before_decode(self):
        data = make_glb()
        self.path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "CODEC_SOURCE_SHA"):
            inspect_glb_container(self.path, "0"*64, len(data))
        with self.assertRaisesRegex(ValueError, "CODEC_SOURCE_SIZE"):
            inspect_glb_container(self.path, hashlib.sha256(data).hexdigest(), len(data)+1)

    def test_truncated_chunk_and_header_fail_closed(self):
        data = make_glb()
        for broken in (data[:10], data[:-1], data[:12]+b"\xff"*8+data[20:]):
            with self.subTest(n=len(broken)):
                with self.assertRaises(ValueError):
                    self.inspect(broken)

    def test_unknown_required_extension_and_duplicate_json_keys_are_rejected(self):
        doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4}],
               "extensionsRequired": ["KHR_bogus_vendor_codec"]}
        with self.assertRaisesRegex(ValueError, "CODEC_EXTENSION_UNSUPPORTED"):
            self.inspect(make_glb(doc))
        a = b'{"asset":{"version":"2.0","version":"3.0"},"buffers":[{"byteLength":4}]}'
        a += b" " * (-len(a) % 4)
        data = (struct.pack("<4sII", b"glTF", 2, 28 + len(a) + 4)
                + struct.pack("<I4s", len(a), b"JSON") + a
                + struct.pack("<I4s", 4, b"BIN\x00") + b"\0"*4)
        with self.assertRaises(ValueError):
            self.inspect(data)

    def test_dimensions_explosion_and_external_resource_fail_closed(self):
        doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4}],
               "accessors": [{} for _ in range(30001)]}
        with self.assertRaisesRegex(ValueError, "CODEC_COMPLEXITY_LIMIT"):
            self.inspect(make_glb(doc))
        doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4, "uri": "https://example.test/e.bin"}]}
        with self.assertRaisesRegex(ValueError, "CODEC_EXTERNAL_RESOURCE"):
            self.inspect(make_glb(doc))

    def test_meshopt_virtual_fallback_is_metadata_only_and_bounded(self):
        doc = {"asset": {"version": "2.0"}, "buffers": [
            {"byteLength": 4}, {"byteLength": 12,
            "extensions": {"EXT_meshopt_compression": {"fallback": True}}}],
            "extensionsRequired": ["EXT_meshopt_compression"],
            "extensionsUsed": ["EXT_meshopt_compression"],
            "bufferViews": [{"buffer": 1, "byteOffset": 0, "byteLength": 12,
                "extensions": {"EXT_meshopt_compression": {
                    "buffer": 0, "byteOffset": 0, "byteLength": 4,
                    "byteStride": 12, "count": 1, "mode": "ATTRIBUTES"}}}]}
        self.assertEqual(self.inspect(make_glb(doc))["required"],
                         ["EXT_meshopt_compression"])
        doc["bufferViews"][0]["extensions"]["EXT_meshopt_compression"]["byteLength"] = 128
        with self.assertRaisesRegex(ValueError, "CODEC_MESHOPT_PAYLOAD_BOUNDS"):
            self.inspect(make_glb(doc))
        doc["buffers"][1]["extensions"]["EXT_meshopt_compression"]["fallback"] = False
        with self.assertRaisesRegex(ValueError, "CODEC_VIRTUAL_BUFFER"):
            self.inspect(make_glb(doc))

    def test_missing_file_and_symlink_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "CODEC_SOURCE_FILE"):
            inspect_glb_container(self.path, "0"*64, 32)
        other = Path(self.temp.name) / "link.glb"
        self.path.write_bytes(make_glb())
        other.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "CODEC_SOURCE_FILE"):
            inspect_glb_container(other, hashlib.sha256(self.path.read_bytes()).hexdigest(), self.path.stat().st_size)

    def test_material_rig_morph_signatures_detect_changes(self):
        doc = {"materials": [{"name": "Mat", "doubleSided": True}],
               "nodes": [{"name": "Hip"}, {"name": "Hand"}],
               "skins": [{"joints": [0, 1]}],
               "animations": [{"name": "Walk", "channels": [{"target": {"node": 1, "path": "rotation"}, "sampler": 0}], "samplers": [{"interpolation": "LINEAR"}]}],
               "meshes": [{"primitives": [{"targets": [{"POSITION": 2}]}]}]}
        base = metadata_signature(doc)
        self.assertEqual(base, metadata_signature(json.loads(json.dumps(doc))))
        doc["skins"][0]["joints"].pop()
        self.assertNotEqual(base["rig"], metadata_signature(doc)["rig"])

    def test_byte_identical_quality_and_real_degradation(self):
        a = np.full((16, 16, 4), 180, dtype=np.uint8)
        a[..., 3] = 255
        p = quality_metrics(a, a)
        self.assertTrue(p["exact_rgba8"])
        self.assertIsNone(p["psnr_db"])
        b = a.copy()
        b[:8, :8, :3] = 0
        p = quality_metrics(a, b)
        self.assertFalse(p["exact_rgba8"])
        self.assertLess(p["ssim_y_8x8"], .98)
        self.assertLess(p["psnr_db"], 40)

    def test_geometry_attributes_detect_shape_and_quantization_drift(self):
        a = np.array([[0., 1., 2.]], dtype=np.float32)
        self.assertTrue(geometry_error(a, a)["exact"])
        self.assertFalse(geometry_error(a, a + .01)["exact"])
        self.assertFalse(geometry_error(a, np.zeros((2, 3)))["aligned"])

    def test_paired_statistics_require_fifteen_complete_runs(self):
        result = paired_statistics([{"file_read_ms": 1.0, "decode_ms": .5, "import_ms": 1.,
                                    "pose_ms": .1, "first_frame_ms": 2.,
                                    "warm_frame_ms": 1.5, "release_ms": .2, "native_wall_ms": 3.0,
                                    "full_frame_digest": "a"*64} for _ in range(15)], 15)
        self.assertEqual(result["n"], 15)
        with self.assertRaisesRegex(ValueError, "CODEC_PAIRS_INCOMPLETE"):
            paired_statistics([{"file_read_ms": 1.0}]*14, 15)


if __name__ == "__main__":
    unittest.main()

