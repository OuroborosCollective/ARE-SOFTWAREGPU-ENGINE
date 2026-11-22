"""Issue #294 RED/GREEN: codec research admission, geometric fidelity and ranking gates.

Fixtures assembled locally are deliberately SYNTHETIC negatives; they are never
presented as licensed asset, render, decoder or benchmark evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import unittest

import numpy as np

from software_gpu.tests.fixtures.glb_resource_fixture import make_resource_glb
from tools.asset_codec_comparison import (
    admit_container,
    compare_arrays,
    compare_frames,
    quality_verdict,
    validate_manifest,
    validate_receipt,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "evidence/asset-codec-khronos-v1.json"


def mutate_fixture(change):
    source = make_resource_glb(1)
    length = struct.unpack_from("<I", source, 12)[0]
    obj = json.loads(source[20:20 + length])
    off = 20 + length
    binary_length = struct.unpack_from("<I", source, off)[0]
    binary = source[off + 8:off + 8 + binary_length]
    change(obj)
    encoded = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    chunks = struct.pack("<I4s", len(encoded), b"JSON") + encoded
    chunks += struct.pack("<I4s", len(binary), b"BIN\\x00") + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


class CodecContractTests(unittest.TestCase):
    def test_khronos_sources_are_licensed_sha_pinned_and_span_static_rig_morph(self):
        manifest = validate_manifest(MANIFEST)
        self.assertEqual(manifest["protocol"], "are.asset-codec-inputs.v1")
        self.assertEqual(manifest["source_revision"], "e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea")
        self.assertGreaterEqual(len(manifest["assets"]), 6)
        self.assertEqual({x["class"] for x in manifest["assets"]},
                         {"static", "rig", "morph"})
        for asset in manifest["assets"]:
            self.assertRegex(asset["sha256"], r"^[a-f0-9]{64}$")
            self.assertGreater(asset["bytes"], 0)
            self.assertIn("/" + manifest["source_revision"] + "/", asset["source_url"])
            self.assertIn("CC-", asset["license"])

    def test_base_glb_admitted_and_compressed_extensions_not_claimed_native(self):
        original = make_resource_glb(1)
        self.assertEqual(admit_container(original)["codec"], "none")
        for extension, place in (
            ("KHR_draco_mesh_compression", "primitive"),
            ("EXT_meshopt_compression", "view"),
        ):
            def change(doc):
                doc["extensionsUsed"] = [extension]
                doc["extensionsRequired"] = [extension]
                if place == "primitive":
                    doc["meshes"][0]["primitives"][0]["extensions"] = {
                        extension: {"bufferView": 0, "attributes": {"POSITION": 0}}
                    }
                else:
                    doc["bufferViews"][0]["extensions"] = {
                        extension: {"buffer": 0, "byteOffset": 0,
                                    "byteLength": 32, "byteStride": 12, "count": 3,
                                    "mode": "ATTRIBUTES", "filter": "NONE"}
                    }
            audited = admit_container(mutate_fixture(change))
            self.assertEqual(audited["codec"], "draco" if place == "primitive" else "meshopt")
            self.assertEqual(audited["native_status"], "unsupported")

    def test_morph_and_unknown_required_extension_remain_unsupported(self):
        def morph(doc):
            doc["meshes"][0]["primitives"][0]["targets"] = [{"POSITION": 0}]
        doc = admit_container(mutate_fixture(morph))
        self.assertEqual(doc["morph_targets"], 1)
        self.assertEqual(doc["native_status"], "unsupported")
        other = admit_container(mutate_fixture(
            lambda doc: doc.update(extensionsRequired=["VENDOR_unknown_ext"])))
        self.assertEqual(other["native_status"], "unsupported")

    def test_bad_bytes_fail_closed_before_any_frame_exists(self):
        raw = make_resource_glb(1)
        for invalid in (raw[:15], raw[:-1], b"bad" + raw[3:]):
            with self.subTest(length=len(invalid)):
                with self.assertRaises(ValueError):
                    admit_container(invalid)
        with self.assertRaises(ValueError):
            admit_container(mutate_fixture(lambda doc: doc["buffers"][0].update(
                byteLength=(1 << 32) + 1)))
        with self.assertRaises(ValueError):
            admit_container(mutate_fixture(lambda doc: doc.update(
                images=[{"uri": "https://example.invalid/resource.png"}])))
        with self.assertRaises(ValueError):
            admit_container(mutate_fixture(lambda doc: doc.update(
                accessors=[{"count": 1 << 60, "type": "VEC3", "componentType": 5126,
                            "bufferView": 0}])))

    def test_attribute_shape_nonfinite_and_exactness_enforced(self):
        a = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        self.assertTrue(compare_arrays(a, a.copy())["exact"])
        drifted = a.copy()
        drifted[0, 0] += np.float32(.03125)
        result = compare_arrays(a, drifted)
        self.assertFalse(result["exact"])
        self.assertAlmostEqual(result["max_abs"], .03125)
        with self.assertRaises(ValueError):
            compare_arrays(a, a[:1])
        with self.assertRaises(ValueError):
            compare_arrays(a, [[float("nan"), 1, 1], [4, 5, 6]])

    def test_psnr_ssim_are_diagnostic_not_frame_parity(self):
        exact = np.zeros((16, 16, 4), dtype=np.uint8)
        exact[:, :, 3] = 255
        baseline_depth = np.ones((16, 16), dtype="<f4")
        one = compare_frames(exact, exact.copy(), baseline_depth, baseline_depth.copy())
        self.assertTrue(one["byte_equal"])
        self.assertTrue(one["depth_equal"])
        self.assertIsNone(one["psnr_db"])  # infinite PSNR serialized as null, not NaN
        self.assertAlmostEqual(one["ssim_7x7"], 1.0, places=7)
        changed = exact.copy()
        changed[0, 0, 0] = 1
        two = compare_frames(exact, changed, baseline_depth, baseline_depth.copy())
        self.assertFalse(two["byte_equal"])
        self.assertTrue(two["psnr_db"] > 40)
        self.assertFalse(quality_verdict(geometry_exact=True, rig_exact=True,
                                        material_exact=True, clip_exact=True,
                                        frame=two))
        changed_depth = baseline_depth.copy()
        changed_depth[0, 0] = np.float32(.5)
        self.assertFalse(compare_frames(exact, exact, baseline_depth, changed_depth)["depth_equal"])

    def test_receipt_requires_actual_fifteen_paired_pipeline_samples(self):
        r = {
            "protocol": "are.asset-codec-comparison.v1",
            "asset_sha256": "a" * 64,
            "original_lod_sha256": "b" * 64,
            "source_revision": "c" * 40,
            "decoder_sha256": "d" * 64,
            "encoder_sha256": "e" * 64,
            "codec_version": "pinned",
            "codec": "meshopt",
            "material_sha256": "f" * 64,
            "rig_sha256": "1" * 64,
            "frame_sha256": "2" * 64,
            "comparable": False,
            "verdict": "NOT_COMPARABLE",
            "raw_runs": [{"file_read_ms": 1.1, "decompression_ms": 1.3,
                          "import_ms": 1.5, "full_frame_ms": 1.7}
                         for _ in range(15)],
        }
        self.assertTrue(validate_receipt(r))
        r["raw_runs"] = r["raw_runs"][:14]
        with self.assertRaises(ValueError):
            validate_receipt(r)
        r["raw_runs"] = [{"file_read_ms": 1, "decompression_ms": 1,
                          "import_ms": 1, "full_frame_ms": 1}
                         for _ in range(15)]
        r["comparable"] = True
        with self.assertRaises(ValueError):
            validate_receipt(r)
        r["verdict"] = "COMPARABLE"
        self.assertTrue(validate_receipt(r))


if __name__ == "__main__":
    unittest.main()
