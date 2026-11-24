"""Synthetic metadata fixtures test admission only; real installers run in CI."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from tools import platform_release, release_gate


SHA = "a" * 40
ANCHOR = "22c436385fad7bf79d074d9eaf2cce458a81810e"
NAMES = {
    "windows-x64": "Windows x64 install / render / uninstall",
    "linux-x86_64": "Linux x86_64 install / render / uninstall",
}


def jobs():
    return {"total_count": 2, "jobs": [
        {"id": index, "run_id": 91, "run_attempt": index,
         "name": name, "status": "completed", "conclusion": "success"}
        for index, name in enumerate(NAMES.values(), 1)
    ]}


def artifacts():
    return {"total_count": 2, "artifacts": [
        {"id": index + 100, "name": f"desktop-{SHA}-{platform}-{index}",
         "expired": False, "size_in_bytes": 4096,
         "digest": "sha256:" + str(index) * 64,
         "workflow_run": {"id": 91, "head_sha": SHA}}
        for index, platform in enumerate(NAMES, 1)
    ]}


def packages(directory):
    """Not executable: deliberately tiny archive-admission fixtures."""
    for platform in NAMES:
        suffix = "windows-x64-setup.exe" if platform == "windows-x64" else "linux-x86_64.run"
        name = "ARE-SoftwareGPU-1.2.50-" + suffix
        data = b"synthetic installer bytes, never executed"
        digest = hashlib.sha256(data).hexdigest()
        (directory / name).write_bytes(data)
        build = {"schema": "are.desktop-release.v1", "platform": platform,
                 "source_sha": SHA, "version": "1.2.50", "source_clean": True,
                 "artifact": {"name": name, "sha256": digest, "bytes": len(data)}}
        smoke = {"schema": "are.desktop-install-smoke.v1", "platform": platform,
                 "source_sha": SHA, "version": "1.2.50", "artifact_sha256": digest,
                 "passed": True,
                 "checks": {x: True for x in ("install", "help", "info", "source", "version", "render", "uninstall")}}
        (directory / f"desktop-{platform}.json").write_text(json.dumps(build), encoding="utf-8")
        (directory / f"desktop-{platform}-smoke.json").write_text(json.dumps(smoke), encoding="utf-8")


class PlatformReleaseGateTests(unittest.TestCase):
    def test_same_first_parent_history_always_uses_same_patch(self):
        lineage = [SHA, "b" * 40, ANCHOR, "c" * 40]
        self.assertEqual("v1.2.2", release_gate.release_tag_for_lineage(lineage, SHA))
        self.assertEqual("v1.2.2", release_gate.release_tag_for_lineage(list(lineage), SHA))

    def test_version_rejects_missing_anchor_wrong_head_and_baseline(self):
        for lineage, sha in (([SHA], SHA), ([SHA, ANCHOR], "b" * 40),
                             ([ANCHOR], ANCHOR), ([SHA, ANCHOR, ANCHOR], SHA)):
            with self.subTest(lineage=lineage), self.assertRaises(release_gate.ReleaseGateError):
                release_gate.release_tag_for_lineage(lineage, sha)

    def test_exact_two_platforms_pass_and_mixed_attempts_keep_their_identity(self):
        selected = release_gate.select_desktop_artifacts(artifacts(), jobs(), 91, SHA)
        self.assertEqual({101, 102}, {item["id"] for item in selected})

    def test_artifacts_reject_wrong_sha_attempt_expiry_duplicate_and_pagination(self):
        variants = []
        for field, value in (("expired", True), ("name", f"desktop-{SHA}-windows-x64-9"),
                             ("digest", "sha256:missing")):
            data = artifacts(); data["artifacts"][0][field] = value; variants.append(data)
        data = artifacts(); data["artifacts"][0]["workflow_run"]["head_sha"] = "b" * 40; variants.append(data)
        data = artifacts(); data["artifacts"].append(copy.deepcopy(data["artifacts"][0])); data["total_count"] = 3; variants.append(data)
        data = artifacts(); data["total_count"] = 3; variants.append(data)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(release_gate.ReleaseGateError):
                release_gate.select_desktop_artifacts(data, jobs(), 91, SHA)

    def test_platform_names_and_success_are_required_not_just_job_count(self):
        for field, value in (("name", "unrelated green job"), ("conclusion", "skipped"),
                             ("run_attempt", 0)):
            data = jobs(); data["jobs"][0][field] = value
            with self.subTest(field=field), self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_desktop_jobs(data, 91)

    def test_release_requires_both_installers_and_byte_bound_completed_smokes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); packages(root)
            result = release_gate.verify_desktop_packages(root, "v1.2.50", SHA)
            self.assertEqual(6, len(result))
            target = root / "ARE-SoftwareGPU-1.2.50-linux-x86_64.run"
            target.write_bytes(target.read_bytes() + b"changed")
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_desktop_packages(root, "v1.2.50", SHA)

    def test_missing_platform_false_smoke_wrong_source_version_and_extra_files_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for field, value in (("passed", False), ("passed", 1), ("source_sha", "b" * 40),
                                 ("version", "1.2.49")):
                packages(root)
                p = root / "desktop-windows-x64-smoke.json"
                data = json.loads(p.read_text()); data[field] = value; p.write_text(json.dumps(data))
                with self.subTest(field=field, value=value), self.assertRaises(release_gate.ReleaseGateError):
                    release_gate.verify_desktop_packages(root, "v1.2.50", SHA)
            packages(root)
            (root / "desktop-windows-x64-smoke.json").unlink()
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_desktop_packages(root, "v1.2.50", SHA)

    def test_dirty_build_is_not_release_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); packages(root)
            p = root / "desktop-windows-x64.json"
            data = json.loads(p.read_text()); data["source_clean"] = False
            p.write_text(json.dumps(data))
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_desktop_packages(root, "v1.2.50", SHA)

    def test_receipt_json_budget_precedes_hashing_and_parsing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); packages(root)
            receipt = root / "desktop-windows-x64.json"
            with receipt.open("ab") as output:
                output.write(b" " * (256 * 1024))
            with self.assertRaisesRegex(release_gate.ReleaseGateError, "JSON.*budget"):
                release_gate.verify_desktop_packages(root, "v1.2.50", SHA)

    def test_existing_release_manifest_must_match_source_version_and_every_byte(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); packages(root)
            files = release_gate.verify_desktop_packages(root, "v1.2.50", SHA)
            manifest = {"schema": "are.platform-release.v1", "source_sha": SHA,
                        "version": "1.2.50", "desktop_run_id": 91, "assets": files}
            release_gate.verify_platform_manifest(manifest, files, "v1.2.50", SHA)
            for key, value in (("source_sha", "b" * 40), ("version", "1.2.51"),
                               ("desktop_run_id", 0), ("assets", files[:-1])):
                with self.subTest(key=key), self.assertRaises(release_gate.ReleaseGateError):
                    release_gate.verify_platform_manifest({**manifest, key: value}, files, "v1.2.50", SHA)
            packages(root)
            (root / "unknown.exe").write_bytes(b"unexpected")
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_desktop_packages(root, "v1.2.50", SHA)

    def test_original_artifact_zip_digest_is_verified_before_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); contents = root / "contents"; contents.mkdir(); packages(contents)
            archive = root / "artifact.zip"
            names = ["ARE-SoftwareGPU-1.2.50-linux-x86_64.run", "desktop-linux-x86_64.json",
                     "desktop-linux-x86_64-smoke.json"]
            with ZipFile(archive, "w") as out:
                for name in names:
                    out.write(contents / name, name)
            expected = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.extract_desktop_artifact(archive, "sha256:" + "0" * 64,
                                                     "linux-x86_64", "v1.2.50", root / "bad")
            self.assertFalse((root / "bad").exists())
            release_gate.extract_desktop_artifact(archive, expected, "linux-x86_64", "v1.2.50", root / "good")
            self.assertEqual(set(names), {p.name for p in (root / "good").iterdir()})

    def test_zip_extra_traversal_and_symlink_entries_fail_before_extraction(self):
        for mode in ("traversal", "missing", "symlink"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); archive = root / "artifact.zip"
                names = ["ARE-SoftwareGPU-1.2.50-linux-x86_64.run", "desktop-linux-x86_64.json",
                         "desktop-linux-x86_64-smoke.json"]
                with ZipFile(archive, "w") as out:
                    for name in (names[:2] if mode == "missing" else names):
                        if mode == "symlink" and name.endswith(".run"):
                            entry = ZipInfo(name); entry.create_system = 3; entry.external_attr = 0o120777 << 16
                            out.writestr(entry, "/outside")
                        else:
                            out.writestr(name, b"synthetic bytes")
                    if mode == "traversal":
                        out.writestr("../outside", "unexpected")
                expected = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
                with self.assertRaises(release_gate.ReleaseGateError):
                    release_gate.extract_desktop_artifact(archive, expected, "linux-x86_64", "v1.2.50", root / "result")
                self.assertFalse((root / "result").exists())


class DownloadBudgetTests(unittest.TestCase):
    """Metadata fixtures and real local transport children, never GitHub/runtime evidence."""

    def release(self, assets):
        return {"tag_name": "v1.2.50", "draft": False, "assets": [
            {"id": index, "name": name, "size": size, "state": "uploaded"}
            for index, (name, size) in enumerate(assets, 1)
        ]}

    def test_all_requested_metadata_is_admitted_before_any_download(self):
        release = self.release([("small.json", 4), ("oversized.json", 256 * 1024 + 1)])
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(platform_release, "api", return_value=release), \
                    patch.object(platform_release.subprocess, "Popen") as process:
                with self.assertRaisesRegex(release_gate.ReleaseGateError, "budget"):
                    platform_release.download_release_files("test/repository", "v1.2.50",
                                                            ["small.json", "oversized.json"], Path(folder))
                process.assert_not_called()
            self.assertEqual([], list(Path(folder).iterdir()))

    def test_download_plan_rejects_ambiguous_unavailable_nonpositive_and_total_budget(self):
        valid = self.release([("a.run", 5)])
        self.assertEqual([valid["assets"][0]], platform_release.release_download_plan(valid, "v1.2.50", ["a.run"]))
        variants = []
        for size in (0, -1, True, "5", 512 * 1024 * 1024 + 1):
            variants.append((self.release([("a.run", size)]), ["a.run"]))
        data = copy.deepcopy(valid); data["assets"][0]["state"] = "new"; variants.append((data, ["a.run"]))
        data = copy.deepcopy(valid); data["assets"].append(copy.deepcopy(data["assets"][0])); variants.append((data, ["a.run"]))
        data = copy.deepcopy(valid); data["tag_name"] = "v1.2.51"; variants.append((data, ["a.run"]))
        variants.extend([(valid, ["absent.run"]), (valid, ["a.run", "a.run"]), (valid, ["../a.run"])])
        data = self.release([(f"{i}.run", 512 * 1024 * 1024) for i in range(3)])
        variants.append((data, [asset["name"] for asset in data["assets"]]))
        for release, names in variants:
            with self.subTest(release=release, names=names), self.assertRaises(release_gate.ReleaseGateError):
                platform_release.release_download_plan(release, "v1.2.50", names)

    def test_real_download_child_must_match_exact_size_and_exit_success(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "asset.bin"
            platform_release.download_to_file([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'good')"], output, 4)
            self.assertEqual(b"good", output.read_bytes())
            for code in ("import sys;sys.stdout.buffer.write(b'bad')",
                         "import sys;sys.stdout.buffer.write(b'excess' * 1000000)",
                         "import sys;sys.stdout.buffer.write(b'good');sys.exit(2)"):
                target = Path(folder) / "rejected.bin"
                with self.subTest(code=code), self.assertRaises(release_gate.ReleaseGateError):
                    platform_release.download_to_file([sys.executable, "-c", code], target, 4)
                self.assertFalse(target.exists(), "partial or excessive downloaded bytes must be removed")
            with self.assertRaises((release_gate.ReleaseGateError, FileExistsError)):
                platform_release.download_to_file([sys.executable, "-c", "print('replace')"], output, 4)
            self.assertEqual(b"good", output.read_bytes())

    def test_action_artifact_budget_rejects_excess_before_transfer(self):
        platform_release.check_download_budget([1024, 4096])
        for sizes in ([0], [True], [512 * 1024 * 1024 + 1], [512 * 1024 * 1024] * 3):
            with self.subTest(sizes=sizes), self.assertRaises(release_gate.ReleaseGateError):
                platform_release.check_download_budget(sizes)


if __name__ == "__main__":
    unittest.main()
