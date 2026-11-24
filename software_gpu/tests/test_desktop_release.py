"""Installer safety contracts using an explicitly synthetic shell payload.

This is not a renderer/runtime acceptance test. The separate native-platform
verify_desktop_install.py runs the real frozen engine after installation.
"""
from pathlib import Path
import contextlib
import gzip
import hashlib
import io
import os
import runpy
import subprocess
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "tools" / "package_desktop.py"


class DesktopReleaseContractTests(unittest.TestCase):
    def builder(self):
        self.assertTrue(BUILDER.is_file(), "No executable desktop packaging path exists")
        return runpy.run_path(str(BUILDER))

    def fixture(self, root):
        bundle = root / "payload"
        bundle.mkdir()
        exe = bundle / "are-softwaregpu"
        exe.write_text("#!/bin/sh\nprintf 'SYNTHETIC_INSTALLER_FIXTURE\\n'\n", encoding="utf-8")
        exe.chmod(0o755)
        (bundle / "LICENSE.md").write_text("test-only license fixture", encoding="utf-8")
        (bundle / "subdirectory").mkdir()
        (bundle / "subdirectory" / "data.txt").write_text("test-only bytes", encoding="utf-8")
        (bundle / "empty_parent" / "nested").mkdir(parents=True)
        return bundle

    def make_installer(self, root):
        builder = self.builder()
        output = root / "example.run"
        builder["build_linux_installer"](self.fixture(root), output, "1.2.50")
        return output

    def test_release_version_rejects_shell_fragments_and_noncanonical_numbers(self):
        validate = self.builder()["validate_version"]
        for bad in ("", "1.2", "v1.2.3", "01.2.3", "1.2.3;touch nope", "1.2.3\n", "1.2.65536"):
            with self.subTest(version=bad), self.assertRaises(ValueError):
                validate(bad)
        self.assertEqual(validate("1.2.50"), "1.2.50")

    def test_failed_native_child_preserves_original_diagnostics(self):
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            verify = runpy.run_path(str(ROOT / "tools" / "verify_desktop_install.py"))
        finally:
            sys.path.pop(0)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                verify["run"]([sys.executable, "-c", "import sys; print('ORIGINAL_CHILD_OUT'); print('ORIGINAL_CHILD_ERROR', file=sys.stderr); sys.exit(7)"], ROOT, dict(os.environ))
        self.assertEqual(caught.exception.returncode, 7)
        self.assertIn("ORIGINAL_CHILD_OUT", stdout.getvalue())
        self.assertIn("ORIGINAL_CHILD_ERROR", stderr.getvalue())

    def test_frame_gate_accepts_real_flat_shaded_triangle_and_rejects_clear_only(self):
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            verify = runpy.run_path(str(ROOT / "tools" / "verify_desktop_install.py"))
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["ARE_SOFTWAREGPU_OUTPUT_DIR"] = tmp
            env["ARE_LEARNING_DB"] = "off"
            subprocess.run([sys.executable, str(ROOT / "main.py"), "--blender"], env=env, check=True, capture_output=True)
            raw = (Path(tmp) / "blender_software_gpu_render.bmp").read_bytes()
            summary = verify["bmp_summary"](raw)
            self.assertGreater(summary["foreground_pixels"], 0)
            self.assertGreater(summary["background_pixels"], 0)
            clear_only = bytearray(raw)
            offset = struct.unpack_from("<I", raw, 10)[0]
            clear_only[offset:] = bytes([42, 34, 30]) * (320 * 240)
            with self.assertRaises(ValueError):
                verify["bmp_summary"](bytes(clear_only))

    def test_desktop_entry_emits_utf8_even_when_parent_environment_requests_cp1252(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        env["PYTHONIOENCODING"] = "cp1252"
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "desktop_entry.py"), "--info"],
                                env=env, check=True, capture_output=True)
        text = result.stdout.decode("utf-8", errors="strict")
        self.assertIn("Device Name:", text)
        self.assertIn("\u2022 mode", text)

    def test_verifier_preserves_utf8_child_output_when_started_with_cp1252_stdout(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "tools")
        env["PYTHONIOENCODING"] = "cp1252"
        code = ("import os,sys; from pathlib import Path; from verify_desktop_install import run; "
                "env=dict(os.environ); env['PYTHONIOENCODING']='utf-8'; "
                "run([sys.executable,'-c',\"print('\\u2022 original')\"],Path.cwd(),env)")
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(result.stdout.decode("utf-8", errors="strict").splitlines(), ["\u2022 original"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux self-extracting installer contract")
    def test_install_run_and_uninstall_preserves_untracked_user_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = self.make_installer(root)
            prefix = root / "installed path with spaces"
            subprocess.run(["sh", str(installer), "--prefix", str(prefix)], check=True, capture_output=True)
            text = subprocess.check_output([str(prefix / "bin" / "are-softwaregpu")], text=True)
            self.assertEqual(text, "SYNTHETIC_INSTALLER_FIXTURE\n")
            self.assertEqual((prefix / "app" / "subdirectory" / "data.txt").read_text(), "test-only bytes")
            keep = prefix / "personal.keep"
            keep.write_text("user data must survive", encoding="utf-8")
            subprocess.run([str(prefix / "uninstall.sh")], check=True, capture_output=True)
            self.assertEqual(keep.read_text(), "user data must survive")
            self.assertEqual(list(prefix.iterdir()), [keep])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux self-extracting installer contract")
    def test_existing_prefix_is_rejected_without_overwriting_its_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = self.make_installer(root)
            prefix = root / "existing"
            prefix.mkdir()
            keep = prefix / "personal.keep"
            keep.write_bytes(b"before")
            result = subprocess.run(["sh", str(installer), "--prefix", str(prefix)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(keep.read_bytes(), b"before")
            self.assertEqual(list(prefix.iterdir()), [keep])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux self-extracting installer contract")
    def test_modified_payload_is_rejected_before_creating_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = self.make_installer(root)
            data = bytearray(installer.read_bytes())
            data[-20] ^= 1
            installer.write_bytes(data)
            prefix = root / "not installed"
            result = subprocess.run(["sh", str(installer), "--prefix", str(prefix)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(prefix.exists())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux self-extracting installer contract")
    def test_relative_prefix_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = self.make_installer(root)
            result = subprocess.run(["sh", str(installer), "--prefix", "relative"], cwd=root, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "relative").exists())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux symlink safety contract")
    def test_uninstall_does_not_follow_replaced_directory_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = self.make_installer(root)
            prefix = root / "installed"
            subprocess.run(["sh", str(installer), "--prefix", str(prefix)], check=True, capture_output=True)
            directory = prefix / "app" / "subdirectory"
            (directory / "data.txt").unlink()
            directory.rmdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / "data.txt").write_text("external user file")
            directory.symlink_to(outside, target_is_directory=True)
            result = subprocess.run([str(prefix / "uninstall.sh")], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((outside / "data.txt").read_text(), "external user file")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux directory inventory safety contract")
    def test_invalid_directory_inventory_is_rejected_before_any_file_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = self.make_installer(root)
            prefix = root / "installed"
            subprocess.run(["sh", str(installer), "--prefix", str(prefix)], check=True, capture_output=True)
            with (prefix / ".are-uninstall-dirs").open("a") as stream:
                stream.write("../outside\n")
            result = subprocess.run([str(prefix / "uninstall.sh")], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((prefix / "bin" / "are-softwaregpu").is_file())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux empty-directory symlink safety contract")
    def test_uninstall_does_not_remove_external_empty_directory_through_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = self.make_installer(root)
            prefix = root / "installed"
            subprocess.run(["sh", str(installer), "--prefix", str(prefix)], check=True, capture_output=True)
            directory = prefix / "app" / "empty_parent"
            (directory / "nested").rmdir()
            directory.rmdir()
            outside = root / "outside"
            (outside / "nested").mkdir(parents=True)
            directory.symlink_to(outside, target_is_directory=True)
            result = subprocess.run([str(prefix / "uninstall.sh")], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((outside / "nested").is_dir())
            self.assertTrue((prefix / "bin" / "are-softwaregpu").is_file())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux failed-extraction cleanup contract")
    def test_bad_archive_with_valid_transport_digest_leaves_no_partial_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = self.make_installer(root)
            header, payload = installer.read_bytes().split(b"\nexit 0\n", 1)
            bad_payload = gzip.compress(b"deliberately invalid synthetic tar payload")
            header = header.replace(hashlib.sha256(payload).hexdigest().encode(), hashlib.sha256(bad_payload).hexdigest().encode())
            installer.write_bytes(header + b"\nexit 0\n" + bad_payload)
            prefix = root / "not installed"
            result = subprocess.run(["sh", str(installer), "--prefix", str(prefix)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(prefix.exists())
            self.assertFalse(list(root.glob(".are-softwaregpu-*")))


if __name__ == "__main__":
    unittest.main()
