"""SHA-pinned independent-asset replay contract (no network; real GLB bytes, no mocks).

The pinned Khronos GLB 2.0 samples are not stored in this repository. These
tests validate the pins, the fail-closed manifest and file checks, and run the
complete replay on real GLB 2.0 bytes generated in-process. Setting
``ARE_GLTF_INDEPENDENT_ASSET_DIR`` to a directory with the pinned originals
additionally replays those (done by the dedicated workflow after a verified
download).
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from software_gpu.tests.test_glb_container_preflight import glb as glb2
from software_gpu.tests.test_glb_diagnostic_evidence import QUAD, make_glb
from tools import gltf21_glb3_independent_assets as independent
from tools.glb_container_preflight import inspect_glb
from tools.gltf21_glb3_sandbox import CONTRACT, inspect_glb3_sandbox

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea"


def local_manifest(folder, files):
    """A manifest over real local GLB 2.0 files, shaped exactly like the pinned one."""
    assets = []
    for name, raw in files.items():
        (Path(folder) / (name + ".glb")).write_bytes(raw)
        assets.append({
            "alias": "local-" + name.lower(), "file": name + ".glb", "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "source_url": "https://raw.githubusercontent.com/KhronosGroup/"
                          "glTF-Sample-Assets/%s/Models/%s/glTF-Binary/%s.glb"
                          % (COMMIT, name, name),
            "license": "generated in this test",
            "expected": independent.replay_asset(raw)})
    document = {"protocol": independent.PROTOCOL, "contract": CONTRACT, "assets": assets}
    path = Path(folder) / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class IndependentAssetManifestTests(unittest.TestCase):
    def test_pinned_manifest_names_four_khronos_samples_at_one_commit(self):
        manifest = independent.load_manifest()
        self.assertEqual(manifest["source_commit"], COMMIT)
        self.assertEqual([asset["alias"] for asset in manifest["assets"]], [
            "khronos-box", "khronos-box-interleaved", "khronos-box-textured",
            "khronos-box-vertex-colors"])
        for asset in manifest["assets"]:
            self.assertIn("/" + COMMIT + "/Models/", asset["source_url"])
            self.assertTrue(asset["license"].startswith("CC-BY-4.0"))
            expected = asset["expected"]
            self.assertEqual(expected["draft_sandbox_on_glb2"], "VERSION_2_OUT_OF_SCOPE")
            self.assertEqual(expected["glb2_preflight"]["bytes"], asset["bytes"])
            self.assertEqual(len(expected["payload_sha256"]), 2)
            wrapped = expected["rewrapped_glb3_draft"]
            self.assertEqual(wrapped["asset_version"], "2.0")
            self.assertEqual(wrapped["draft_features_observed"], ["glb_container_v3"])
            # Draft header and chunk headers are 4 + 2 x 8 bytes longer than GLB2.
            self.assertGreaterEqual(wrapped["bytes"], asset["bytes"] + 20)
            self.assertLessEqual(wrapped["bytes"], asset["bytes"] + 20 + 7)
        tracked = subprocess.run(["git", "ls-files", "*.glb"], cwd=ROOT, text=True,
                                 capture_output=True, timeout=30)
        self.assertEqual(tracked.returncode, 0)
        self.assertNotIn("Box", tracked.stdout)

    def test_manifest_with_foreign_host_path_or_digest_is_refused(self):
        good = json.loads(independent.MANIFEST.read_text(encoding="utf-8"))
        url = good["assets"][0]["source_url"]
        changes = [
            ("PROTOCOL", lambda d: d.update(protocol="other")),
            ("CONTRACT", lambda d: d.update(contract="are.gltf21-glb3-sandbox.v2")),
            ("COUNT", lambda d: d.update(assets=[])),
            ("ALIAS", lambda d: d["assets"][1].update(alias=d["assets"][0]["alias"])),
            ("ALIAS", lambda d: d["assets"][0].update(alias="../box")),
            ("FILE", lambda d: d["assets"][0].update(file="../../Box.glb")),
            ("HASH_OR_SIZE", lambda d: d["assets"][0].update(sha256="0" * 63)),
            ("HASH_OR_SIZE", lambda d: d["assets"][0].update(bytes=10 ** 9)),
            ("HASH_OR_SIZE", lambda d: d["assets"][0].update(bytes=True)),
            ("SOURCE", lambda d: d["assets"][0].update(
                source_url=url.replace("https://", "http://"))),
            ("SOURCE", lambda d: d["assets"][0].update(
                source_url=url.replace("raw.githubusercontent.com", "evil.example"))),
            ("SOURCE", lambda d: d["assets"][0].update(
                source_url=url.replace(COMMIT, "main"))),
            ("SOURCE", lambda d: d["assets"][0].update(
                source_url=url.replace("KhronosGroup", "someone-else"))),
            ("SOURCE", lambda d: d["assets"][0].update(source_url=url + "?x=1")),
            ("SOURCE", lambda d: d["assets"][0].update(
                source_url=url.replace("/Models/", "/Models/../Models/"))),
            ("LICENSE", lambda d: d["assets"][0].update(license="")),
            ("EXPECTED", lambda d: d["assets"][0].pop("expected")),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            for code, change in changes:
                document = copy.deepcopy(good)
                change(document)
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "INDEPENDENT_ASSET_" + code):
                    independent.load_manifest(path)


class IndependentAssetReplayTests(unittest.TestCase):
    def setUp(self):
        self.files = {
            "Quad": make_glb(QUAD, [(0, 1, 2), (0, 2, 3)],
                             [(0, 0), (1, 0), (1, 1), (0, 1)]),
            "JsonOnly": glb2({"asset": {"version": "2.0"}}),
            "Embedded": glb2({"asset": {"version": "2.0"},
                              "buffers": [{"byteLength": 5}]}, b"hello"),
        }

    def test_real_glb2_bytes_replay_through_both_disjoint_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = independent.load_manifest(local_manifest(folder, self.files))
            report = independent.replay(folder, manifest)
            self.assertEqual(report["status"], "PASS")
            self.assertIs(report["ratification_claimed"], False)
            self.assertEqual(report["runtime_admission"], "refused")
            self.assertIs(report["assets_modified"], False)
            for name, raw in self.files.items():
                self.assertEqual((Path(folder) / (name + ".glb")).read_bytes(), raw)
            quad = report["results"][0]["replay"]
            self.assertEqual(quad["draft_sandbox_on_glb2"], "VERSION_2_OUT_OF_SCOPE")
            self.assertEqual(quad["glb2_preflight"], inspect_glb(self.files["Quad"]))
            self.assertEqual(quad["rewrapped_glb3_draft"]["buffer_views_checked"], 3)
            self.assertEqual(quad["rewrapped_glb3_draft"]["accessors_checked"], 3)
            self.assertEqual(len(report["results"][1]["replay"]["payload_sha256"]), 1)

    def test_rewrap_keeps_payload_bytes_and_stays_out_of_the_glb2_path(self):
        raw = self.files["Quad"]
        json_payload, binary_payload = independent.split_glb2(raw)
        wrapped = independent.rewrap_as_glb3_draft(json_payload, binary_payload)
        receipt = inspect_glb3_sandbox(wrapped, contract=CONTRACT)
        chunks = receipt["container"]["chunks"]
        self.assertEqual([chunk["sha256"] for chunk in chunks],
                         [hashlib.sha256(json_payload).hexdigest(),
                          hashlib.sha256(binary_payload).hexdigest()])
        self.assertEqual(wrapped[chunks[1]["offset"]:][:len(binary_payload)],
                         binary_payload)
        self.assertEqual(chunks[1]["offset"] % 8, 0)
        self.assertEqual(receipt["gltf"]["buffers"],
                         [{"source": "glb_chunk_implicit", "chunk": 1,
                           "byte_length": json.loads(json_payload)["buffers"][0]
                           ["byteLength"]}])
        with self.assertRaisesRegex(ValueError, "GLB version/length mismatch"):
            inspect_glb(wrapped)
        self.assertEqual(independent.split_glb2(self.files["JsonOnly"])[1], None)

    def test_tampered_file_changed_expectation_or_missing_file_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = local_manifest(folder, self.files)
            manifest = independent.load_manifest(path)
            drifted = copy.deepcopy(manifest)
            drifted["assets"][0]["expected"]["rewrapped_glb3_draft"]["receipt_sha256"] = (
                "0" * 64)
            with self.assertRaisesRegex(ValueError, "REPLAY_DRIFT:local-quad"):
                independent.replay(folder, drifted)
            target = Path(folder) / "Quad.glb"
            data = bytearray(target.read_bytes())
            data[-1] ^= 1
            target.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "INDEPENDENT_ASSET_HASH_MISMATCH"):
                independent.replay(folder, manifest)
            target.write_bytes(data[:-4])
            with self.assertRaisesRegex(ValueError, "INDEPENDENT_ASSET_SIZE_MISMATCH"):
                independent.replay(folder, manifest)
            target.unlink()
            with self.assertRaisesRegex(ValueError, "INDEPENDENT_ASSET_SIZE_MISMATCH"):
                independent.replay(folder, manifest)
            failed = subprocess.run(
                [sys.executable, "-m", "tools.gltf21_glb3_independent_assets",
                 "--assets-dir", folder, "--manifest", str(path)],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(failed.returncode, 2)
            self.assertIn("INDEPENDENT_REPLAY_REJECTED", failed.stderr)

    def test_cli_replay_writes_a_report_and_rebuild_keeps_the_asset_pins(self):
        with tempfile.TemporaryDirectory() as folder:
            path = local_manifest(folder, self.files)
            before = json.loads(path.read_text(encoding="utf-8"))
            receipt = Path(folder) / "out" / "replay.json"
            done = subprocess.run(
                [sys.executable, "-m", "tools.gltf21_glb3_independent_assets",
                 "--assets-dir", folder, "--manifest", str(path), "--rebuild-expected",
                 "--receipt", str(receipt)],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads(done.stdout), {"assets": 3, "status": "PASS"})
            report = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["protocol"], independent.REPORT_PROTOCOL)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), before)

    def test_pinned_originals_replay_when_a_verified_directory_is_provided(self):
        manifest = independent.load_manifest()
        directory = os.environ.get("ARE_GLTF_INDEPENDENT_ASSET_DIR")
        if directory:
            report = independent.replay(directory, manifest)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(len(report["results"]), 4)
            print("GLB3_INDEPENDENT_REPLAY assets=4 status=PASS", flush=True)
        else:
            # Without the originals nothing is downloaded and nothing passes.
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError, "INDEPENDENT_ASSET_SIZE_MISMATCH"):
                    independent.replay(folder, manifest)
                self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
