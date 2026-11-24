"""Release admission tests, not Mozilla signing or store/runtime evidence."""
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
from contextlib import redirect_stdout

from tools import package_firefox_addon as package

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
VERSION = "1.2.50"


class FirefoxReleaseTests(unittest.TestCase):
    def helper(self):
        self.assertTrue((ROOT / "tools/firefox_release.py").is_file(), "No version-bound Firefox release admission exists")
        return importlib.import_module("tools.firefox_release")

    def fixture(self, directory):
        """Real source bytes with explicit synthetic source attestation for unit admission."""
        xpi = directory / f"are-softwaregpu-diagnostics-{VERSION}-unsigned.xpi"
        receipt = package.build_package(ROOT / "clients/firefox-addon", xpi, VERSION)
        sources = package.read_entries(ROOT, package.SOURCE_FILES)
        sources["clients/firefox-addon/manifest.json"] = package.runtime_entries(ROOT / "clients/firefox-addon", VERSION)["manifest.json"]
        receipt["sourceArchive"] = package.write_archive(sources, directory / f"are-softwaregpu-diagnostics-{VERSION}-source.zip")
        receipt["sourceFiles"] = [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                                  for name, data in sources.items()]
        receipt.update({"source_sha": SHA, "source_clean": True})
        (directory / "package-receipt.json").write_text(json.dumps(receipt))
        return receipt

    def test_unsigned_admission_binds_both_archives_version_source_and_receipt(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            receipt = helper.verify_unsigned_package(root, VERSION, SHA)
            self.assertFalse(receipt["signed"])
            self.assertEqual(receipt["version"], VERSION)
            self.assertEqual(receipt["source_sha"], SHA)
            xpi = root / receipt["package"]["name"]
            xpi.write_bytes(xpi.read_bytes() + b"tampered")
            with self.assertRaises(ValueError):
                helper.verify_unsigned_package(root, VERSION, SHA)

    def test_dirty_source_wrong_version_and_wrong_source_sha_are_refused(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = self.fixture(root)
            for key, value in (("source_clean", False), ("signed", True), ("version", "0.1.0"), ("source_sha", "b" * 40)):
                changed = {**receipt, key: value}
                (root / "package-receipt.json").write_text(json.dumps(changed))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    helper.verify_unsigned_package(root, VERSION, SHA)

    def test_amo_configuration_preserves_custom_license_and_project_links(self):
        metadata = self.helper().amo_metadata()
        self.assertNotIn("license", metadata["version"])
        self.assertEqual(metadata["version"]["custom_license"]["text"]["en-US"], (ROOT / "LICENSE.md").read_text())
        self.assertIn("arelogic.space", metadata["homepage"]["en-US"])
        self.assertIn("OuroborosCollective/ARE-SOFTWAREGPU-ENGINE", metadata["support_url"]["en-US"])

    def test_amo_presence_requires_both_credentials_and_reports_only_booleans(self):
        presence = self.helper().credential_presence
        self.assertEqual(presence({}), {"AMO_JWT_ISSUER": False, "AMO_JWT_SECRET": False})
        self.assertEqual(presence({"AMO_JWT_ISSUER": "unit-issuer", "AMO_JWT_SECRET": "unit-secret"}),
                         {"AMO_JWT_ISSUER": True, "AMO_JWT_SECRET": True})

    def test_mozilla_pending_wrong_channel_or_version_never_count_as_published(self):
        helper = self.helper()
        good = {"version": VERSION, "channel": "listed", "file": {"status": "public", "hash": "sha256:" + "1" * 64,
                "url": "https://addons.mozilla.org/firefox/downloads/file/123/example.xpi"}}
        self.assertEqual(helper.accepted_amo_file(good, VERSION), good["file"])
        for changed in ({**good, "version": "0.1.0"}, {**good, "channel": "unlisted"},
                        {**good, "file": {**good["file"], "status": "unreviewed"}},
                        {**good, "file": {**good["file"], "url": "http://invalid.example/xpi"}}):
            with self.assertRaises(ValueError):
                helper.accepted_amo_file(changed, VERSION)

    def test_signed_download_must_preserve_every_runtime_byte(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = self.fixture(root)
            unsigned = root / receipt["package"]["name"]
            signed = root / "synthetic-signed-container.xpi"
            # Fake signature is deliberately only a container test, never signing evidence.
            with zipfile.ZipFile(unsigned) as source, zipfile.ZipFile(signed, "w") as target:
                for name in source.namelist():
                    target.writestr(name, source.read(name))
                target.writestr("META-INF/mozilla.rsa", b"unit-test marker; not a certificate")
            helper.verify_signed_payload(unsigned, signed)
            with zipfile.ZipFile(signed, "a") as archive:
                archive.writestr("extra-script.js", b"unreviewed runtime")
            with self.assertRaises(ValueError):
                helper.verify_signed_payload(unsigned, signed)

    def test_public_file_does_not_override_a_private_or_disabled_listing(self):
        helper = self.helper()
        listing = {"guid": helper.ADDON_ID, "type": "extension", "status": "public", "is_disabled": False,
                   "url": "https://addons.mozilla.org/en-US/firefox/addon/are-softwaregpu-diagnostics/"}
        self.assertEqual(helper.accepted_amo_listing(listing), listing["url"])
        for changes in ({"status": "nominated"}, {"is_disabled": True}, {"guid": "other@example.test"},
                        {"url": "https://unrelated.example/"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                helper.accepted_amo_listing({**listing, **changes})

    def test_secretless_signing_fails_before_network_or_package_mutation(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            root = Path(temporary)
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaisesRegex(ValueError, "BLOCKED_AMO_CREDENTIALS"):
                helper.sign_with_amo(root, root / "stage", VERSION, SHA, "must-not-be-executed")
            self.assertEqual(list(root.iterdir()), [])
            self.assertEqual(json.loads(output.getvalue())["credential_presence"],
                             {"AMO_JWT_ISSUER": False, "AMO_JWT_SECRET": False})

    def test_submission_tool_failure_is_not_overridden_by_later_readback(self):
        helper = self.helper()
        # External transport/process doubles only: this is not AMO signing evidence.
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ,
                {"AMO_JWT_ISSUER": "unit-issuer", "AMO_JWT_SECRET": "unit-secret"}, clear=True):
            root = Path(temporary)
            self.fixture(root)
            with patch.object(helper, "amo_version", return_value=None) as lookup, \
                 patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=2, stdout="unit upload failure")), \
                 redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "AMO_SUBMISSION_TOOL_FAILED_EXIT_2"):
                helper.sign_with_amo(root, root / "stage", VERSION, SHA, "unit-web-ext")
            self.assertEqual(lookup.call_count, 1)

    def test_archive_admission_refuses_traversal_absolute_symlink_and_duplicates(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, name in enumerate(("../escape", "/absolute", "C:/absolute", "directory\\escape", "linked")):
                archive = root / f"bad-{index}.zip"
                info = zipfile.ZipInfo(name)
                info.external_attr = ((stat.S_IFLNK if name == "linked" else stat.S_IFREG) | 0o644) << 16
                with zipfile.ZipFile(archive, "w") as output:
                    output.writestr(info, b"payload")
                with self.subTest(name=name), self.assertRaises(ValueError):
                    helper.archive_entries(archive)
            duplicate = root / "duplicate.zip"
            with self.assertWarns(UserWarning), zipfile.ZipFile(duplicate, "w") as output:
                output.writestr("manifest.json", b"first")
                output.writestr("manifest.json", b"second")
            with self.assertRaises(ValueError):
                helper.archive_entries(duplicate)

    def test_unsigned_public_receipt_and_checksum_are_exact_and_staged_version_is_real(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            stage = root / "staged"
            helper.prepare_unsigned(root, VERSION, SHA, stage)
            self.assertEqual(json.loads((stage / "manifest.json").read_text())["version"], VERSION)
            helper.verify_public_files(root, VERSION, SHA)
            (root / helper.unsigned_names(VERSION)[3]).write_text("unrelated checksum\n")
            with self.assertRaisesRegex(ValueError, "FIREFOX_PUBLIC_CHECKSUMS_CHANGED"):
                helper.verify_public_files(root, VERSION, SHA)


if __name__ == "__main__":
    unittest.main()
