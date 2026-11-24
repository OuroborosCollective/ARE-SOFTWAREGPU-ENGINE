"""Package boundaries, not browser/GPU runtime evidence."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from tools.package_firefox_addon import build_package, FILES, read_entries, write_archive, SOURCE_FILES

ROOT = Path(__file__).resolve().parents[2]


class FirefoxAddonPackageTests(unittest.TestCase):
    def test_release_version_is_staged_without_changing_source_and_rebuilds(self):
        source_manifest = ROOT / "clients/firefox-addon/manifest.json"
        before = source_manifest.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "release"
            result = subprocess.run([sys.executable, "tools/package_firefox_addon.py", "--version", "1.2.50",
                                     "--output-dir", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            package = output / "are-softwaregpu-diagnostics-1.2.50-unsigned.xpi"
            with zipfile.ZipFile(package) as archive:
                self.assertEqual(json.loads(archive.read("manifest.json"))["version"], "1.2.50")
                self.assertEqual(archive.read("diagnostics.mjs"), (ROOT / "clients/firefox-addon/diagnostics.mjs").read_bytes())
            unpacked = root / "source"
            with zipfile.ZipFile(output / "are-softwaregpu-diagnostics-1.2.50-source.zip") as archive:
                archive.extractall(unpacked)
            rebuilt = root / "rebuilt"
            subprocess.run([sys.executable, "tools/package_firefox_addon.py", "--version", "1.2.50",
                            "--output-dir", str(rebuilt)], cwd=unpacked, check=True, capture_output=True)
            self.assertEqual(package.read_bytes(), (rebuilt / package.name).read_bytes())
            receipt = json.loads((output / "package-receipt.json").read_text())
            self.assertFalse(receipt["signed"])
            self.assertEqual(receipt["version"], "1.2.50")
            self.assertEqual(source_manifest.read_bytes(), before)

    def test_release_version_refuses_noncanonical_or_unsafe_manifest_values(self):
        for bad in ("v1.2.50", "01.2.50", "1.2", "1.2.50;whoami", "1.2.65536", "1.2.50-rc.1"):
            with self.subTest(version=bad), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run([sys.executable, "tools/package_firefox_addon.py", "--version", bad,
                                         "--output-dir", directory], cwd=ROOT, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ADDON_RELEASE_VERSION_INVALID", result.stderr)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_source_revision_cannot_be_asserted_by_an_unrelated_cli_argument(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "tools/package_firefox_addon.py", "--version", "1.2.50",
                                     "--source-sha", "0" * 40, "--output-dir", directory],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ADDON_SOURCE_REVISION_MISMATCH", result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_source_archive_rebuilds_identical_runtime_without_repository_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_zip = root / "source.zip"
            write_archive(read_entries(ROOT, SOURCE_FILES), source_zip)
            unpacked = root / "unpacked"
            with zipfile.ZipFile(source_zip) as archive:
                archive.extractall(unpacked)
            subprocess.run([sys.executable, "tools/package_firefox_addon.py", "--output-dir", "build"],
                           cwd=unpacked, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            current = root / "current.xpi"
            build_package(ROOT / "clients/firefox-addon", current)
            self.assertEqual(current.read_bytes(), (unpacked / "build/are-softwaregpu-diagnostics-0.1.0.xpi").read_bytes())

    def test_reproducible_archive_contains_exact_source_and_license_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first.xpi", Path(directory) / "second.xpi"
            source = ROOT / "clients/firefox-addon"
            manifest = build_package(source, first)
            build_package(source, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(manifest["version"], "0.1.0")
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.namelist(), sorted(FILES))
                for name in FILES:
                    self.assertEqual(archive.read(name), (source / name).read_bytes())
            self.assertEqual((source / "LICENSE.md").read_bytes(), (ROOT / "LICENSE.md").read_bytes())
            self.assertEqual((source / "NOTICE").read_bytes(), (ROOT / "NOTICE").read_bytes())

    def test_cannot_silently_package_permissions_or_remote_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            shutil.copytree(ROOT / "clients/firefox-addon", source)
            path = source / "manifest.json"
            original = json.loads(path.read_text(encoding="utf-8"))
            for key, value in [("permissions", ["tabs"]), ("host_permissions", ["<all_urls>"]), ("content_scripts", [{"matches": ["<all_urls>"]}])]:
                with self.subTest(key=key):
                    path.write_text(json.dumps({**original, key: value}), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "PERMISSION_BOUNDARY"):
                        build_package(source, Path(directory) / "bad.xpi")
            altered = json.loads(json.dumps(original))
            altered["content_security_policy"]["extension_pages"] = "script-src 'self'; connect-src https:"
            path.write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "NETWORK_BOUNDARY"):
                build_package(source, Path(directory) / "bad.xpi")

    def test_unlisted_files_are_excluded_and_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            shutil.copytree(ROOT / "clients/firefox-addon", source)
            (source / "private-test-fixture.txt").write_text("unit-test marker", encoding="utf-8")
            destination = Path(directory) / "addon.xpi"
            build_package(source, destination)
            before = destination.read_bytes()
            with zipfile.ZipFile(destination) as archive:
                self.assertNotIn("private-test-fixture.txt", archive.namelist())
            with self.assertRaises(FileExistsError):
                build_package(source, destination)
            self.assertEqual(destination.read_bytes(), before)

    def test_duplicate_csp_cannot_hide_a_permissive_first_directive(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            shutil.copytree(ROOT / "clients/firefox-addon", source)
            path = source / "manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            for policy in (
                "connect-src https:; connect-src 'none'; script-src 'self'",
                "script-src https:; script-src 'self'; connect-src 'none'",
                "Connect-Src https:; connect-src 'none'; script-src 'self'",
            ):
                with self.subTest(policy=policy):
                    manifest["content_security_policy"]["extension_pages"] = policy
                    path.write_text(json.dumps(manifest), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "DUPLICATE_CSP"):
                        build_package(source, Path(directory) / "bad.xpi")

    def test_non_regular_input_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            shutil.copytree(ROOT / "clients/firefox-addon", source)
            path = source / "background.js"
            path.unlink()
            path.mkdir()
            with self.assertRaisesRegex(ValueError, "NOT_REGULAR"):
                build_package(source, Path(directory) / "bad.xpi")


if __name__ == "__main__":
    unittest.main()
