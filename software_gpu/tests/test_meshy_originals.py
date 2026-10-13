"""Negative checksum and zero-network validation for owner-approved original GLBs."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.meshy_originals import load_manifest,verify,fetch_one


class TestMeshyOriginals(unittest.TestCase):
    def test_pinned_assets_and_large_maize_explicitly_blocked(self):
        assets=load_manifest()["assets"]
        self.assertEqual([x["alias"] for x in assets],["azure-knight","crimson-dragon","maize-field"])
        self.assertEqual(assets[2]["triangles"],7653974)
        self.assertIsNone(assets[2]["source_url"])
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,"MESHY_PUBLIC_SOURCE_NOT_READY"):
                fetch_one(assets[2],Path(folder)/"maize.glb")

    def test_truncation_and_hash_forgery_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"sample.glb"
            original=load_manifest()["assets"][0]
            path.write_bytes(b"glTF" + b"x"*32)
            forged=dict(original,bytes=path.stat().st_size)
            with self.assertRaisesRegex(ValueError,"MESHY_HASH_MISMATCH"):
                verify(path,forged)
            path.write_bytes(b"FAKE")
            with self.assertRaisesRegex(ValueError,"MESHY_SIZE_MISMATCH"):
                verify(path,original)

    def test_manifest_rejects_replaced_untrusted_host_and_bad_digest(self):
        obj=load_manifest()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"manifest.json"
            obj["assets"][0]["source_url"]="https://evil.example/knight.glb"
            path.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ValueError,"MESHY_SOURCE_HOST"):
                load_manifest(path)
            obj["assets"][0]["source_url"]="https://d2ol7oe51mr4n9.cloudfront.net/test"
            obj["assets"][0]["sha256"]="0"*63
            path.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ValueError,"MESHY_HASH_OR_SIZE"):
                load_manifest(path)
