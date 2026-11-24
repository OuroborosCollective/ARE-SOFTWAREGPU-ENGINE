"""Synthetic metadata tests; real APK install/signature evidence is produced in CI."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tools import release_gate
from tools import android_release
from tools.android_emulator_smoke import assert_serial_unused


class AndroidReleaseTests(unittest.TestCase):
    def test_existing_emulator_device_or_offline_serial_is_never_reused(self):
        assert_serial_unused("List of devices attached\nemulator-5556\tdevice\n", "emulator-5554")
        for state in ("device", "offline", "unauthorized"):
            with self.subTest(state=state), self.assertRaises(release_gate.ReleaseGateError):
                assert_serial_unused("List of devices attached\nemulator-5554\t" + state + "\n", "emulator-5554")

    def test_semver_version_code_is_unique_ordered_and_retry_stable(self):
        versions = ("v0.0.1", "v0.99.99999", "v1.0.0", "v1.2.49", "v1.2.50", "v1.3.0", "v2.0.0")
        codes = [release_gate.android_version(tag)["version_code"] for tag in versions]
        self.assertEqual(codes, sorted(set(codes)))
        self.assertEqual(10200050, release_gate.android_version("v1.2.50")["version_code"])
        self.assertEqual(release_gate.android_version("v1.2.50"), release_gate.android_version("v1.2.50"))

    def test_version_code_rejects_collisions_prereleases_and_overflow(self):
        for tag in ("v0.0.0", "v1.100.0", "v1.2.100000", "v210.0.1", "v01.2.3", "v1.2.3-rc.1", "v1.2.3+build"):
            with self.subTest(tag=tag), self.assertRaises(release_gate.ReleaseGateError):
                release_gate.android_version(tag)

    def test_apk_package_version_sdk_and_release_variant_must_match(self):
        badging = "package: name='de.arelorian.softwaregpu' versionCode='10200050' versionName='1.2.50' platformBuildVersionName='15'\nsdkVersion:'26'\ntargetSdkVersion:'35'\n"
        release_gate.verify_android_badging(badging, "v1.2.50")
        for old, new in (("softwaregpu", "malicious"), ("10200050", "1"), ("1.2.50", "1.0"), ("'26'", "'25'"), ("'35'", "'34'")):
            with self.subTest(new=new), self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_android_badging(badging.replace(old, new), "v1.2.50")
        with self.assertRaises(release_gate.ReleaseGateError):
            release_gate.verify_android_badging(badging + "application-debuggable\n", "v1.2.50")

    def test_signature_requires_single_non_debug_certificate_and_v2(self):
        output = "Verified using v2 scheme (APK Signature Scheme v2): true\nSigner #1 certificate DN: CN=ARE Release\nSigner #1 certificate SHA-256 digest: " + "a" * 64 + "\n"
        self.assertEqual("a" * 64, release_gate.android_signer_fingerprint(output, "release"))
        for data in (output.replace(": true", ": false"), output.replace("ARE Release", "Android Debug"), output + "Signer #2 certificate SHA-256 digest: " + "b" * 64 + "\n"):
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.android_signer_fingerprint(data, "release")
        ci = output.replace("ARE Release", "ARE CI TEST ONLY")
        self.assertEqual("a" * 64, release_gate.android_signer_fingerprint(ci, "ci-test"))
        with self.assertRaises(release_gate.ReleaseGateError):
            release_gate.android_signer_fingerprint(ci, "release")

    def test_embedded_source_receipt_is_required_and_byte_bound(self):
        sha = "b" * 40
        expected = {"schema": "are.android-source.v1", "version": "1.2.50", "version_code": 10200050, "source_sha": sha, "runtime": "https-companion"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.apk"
            for key, value in ((None, None), ("source_sha", "c" * 40), ("version_code", 1), ("runtime", "native-renderer")):
                payload = copy.deepcopy(expected)
                if key:
                    payload[key] = value
                with ZipFile(path, "w") as archive:
                    archive.writestr("assets/are-release.json", json.dumps(payload))
                if key:
                    with self.assertRaises(release_gate.ReleaseGateError):
                        release_gate.verify_android_source(path, "v1.2.50", sha)
                else:
                    self.assertEqual(expected, release_gate.verify_android_source(path, "v1.2.50", sha))

    def test_partial_prior_apk_upload_already_establishes_signing_lineage(self):
        # API/SDK doubles exercise admission only; CI separately executes real apksigner.
        release = {"tag_name": "v1.2.49", "draft": False, "assets": [
            {"name": "ARE-SoftwareGPU-1.2.49-android-companion.apk"}]}
        with patch.object(android_release.platform, "api", return_value=[release]), \
                patch.object(android_release.platform, "download_release_files"), \
                patch.object(android_release, "verify_apk", return_value={"signer_certificate_sha256": "a" * 64}), \
                patch.object(android_release, "tag_commit", return_value="b" * 40):
            with self.assertRaises(release_gate.ReleaseGateError):
                android_release.verify_signer_continuity(android_release.REPOSITORY, "b" * 64)

    def test_missing_production_signing_settings_fail_without_generating_a_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(release_gate.ReleaseGateError):
                android_release.signing_environment(directory, False)
            self.assertFalse((Path(directory) / "signing.jks").exists())

    def test_ci_scope_wrong_device_and_wrong_api_cannot_authorize_production_receipt(self):
        sha = "d" * 40
        metadata = {"artifact": {"sha256": "e" * 64}, "signer_certificate_sha256": "a" * 64}
        smoke = {"schema": "are.android-emulator-smoke.v1", "passed": True,
                 "source_sha": sha, "version": "1.2.50", "apk_sha256": "e" * 64,
                 "signing_scope": "release", "device_kind": "emulator", "android_api": 35,
                 "checks": {key: True for key in ("install", "launch", "process_alive", "welcome_ui", "installed_apk_bytes", "uninstall")}}
        with tempfile.TemporaryDirectory() as directory, patch.object(android_release, "verify_apk", return_value=metadata):
            output = Path(directory)
            (output / android_release.apk_name("v1.2.50")).write_bytes(b"synthetic admission fixture")
            path = output / "smoke.json"
            for key, value in (("signing_scope", "ci-test"), ("device_kind", "physical"), ("android_api", 34), ("android_api", "35")):
                path.write_text(json.dumps({**smoke, key: value}), encoding="utf-8")
                with self.subTest(key=key, value=value), self.assertRaises(release_gate.ReleaseGateError):
                    android_release.complete_receipt(output, "v1.2.50", sha, path, "release")


if __name__ == "__main__":
    unittest.main()
