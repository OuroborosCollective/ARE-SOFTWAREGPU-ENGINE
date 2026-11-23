"""Source-bound Vulkan Loader reference tests, never an ARE-ICD success."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from software_gpu.drivers.vulkan_reference import (
    validate_reference_manifest,
    verify_reference_summary,
    run_reference_probe,
)


class TestVulkanLoaderReference(unittest.TestCase):
    def test_manifest_must_be_a_real_lavapipe_icd_and_not_are(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "lvp_icd.x86_64.json"
            for content in (
                {"file_format_version": "1.0.0", "ICD": {"library_path": "are_driver.so", "api_version": "1.3.0"}},
                {"file_format_version": "1.0.0", "ICD": {"library_path": "libvulkan_lvp.so", "api_version": "fake"}},
                {"file_format_version": "1.0.0", "ICD": {"library_path": "../../libvulkan_lvp.so", "api_version": "1.3.0"}},
                {"file_format_version": "1.0.0", "ICD": {"library_path": "libvulkan_lvp.so", "api_version": "1.3.0", "unknown": "x"}},
            ):
                path.write_text(json.dumps(content), encoding="utf-8")
                with self.assertRaises(ValueError):
                    validate_reference_manifest(path)
            path.write_text(json.dumps({"file_format_version": "1.0.0", "ICD":
                {"library_path": "libvulkan_lvp.so", "api_version": "1.3.0"}}), encoding="utf-8")
            with patch("software_gpu.drivers.vulkan_reference._resolve_system_library",
                       return_value=Path("/usr/lib/libvulkan_lvp.so")):
                self.assertEqual(validate_reference_manifest(path)["library_name"], "libvulkan_lvp.so")

    def test_library_must_resolve_inside_system_directories(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            system = root / "system"
            system.mkdir()
            outside = root / "outside"
            outside.mkdir()
            library = outside / "libvulkan_lvp.so"
            library.touch()  # Inert fixture; no native code is loaded.
            alias = system / library.name
            alias.symlink_to(library)
            manifest = root / "lvp_icd.json"
            with patch("software_gpu.drivers.vulkan_reference._SYSTEM_LIBRARY_DIRS", (system,)), \
                    patch("software_gpu.drivers.vulkan_reference.subprocess.run") as launch:
                for declared in (system / ".." / "outside" / library.name, alias):
                    with self.subTest(declared=declared):
                        manifest.write_text(json.dumps({"file_format_version": "1.0.0", "ICD":
                            {"library_path": str(declared), "api_version": "1.3.0"}}), encoding="utf-8")
                        with self.assertRaisesRegex(ValueError, "VULKAN_REFERENCE_UNTRUSTED_LIBRARY"):
                            run_reference_probe(manifest)
                launch.assert_not_called()

    def test_summary_must_contain_true_cpu_physical_device(self):
        with self.assertRaises(ValueError):
            verify_reference_summary("deviceName = Ouroboros ARE SoftwareGPU\ndeviceType = PHYSICAL_DEVICE_TYPE_CPU")
        with self.assertRaises(ValueError):
            verify_reference_summary("deviceName = llvmpipe\ndeviceType = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU")
        with self.assertRaises(ValueError):
            verify_reference_summary("deviceName = llvmpipe\n")
        result = verify_reference_summary(
            "GPU0:\n deviceType = PHYSICAL_DEVICE_TYPE_CPU\n deviceName = llvmpipe (LLVM)\n")
        self.assertEqual(result["device_name"], "llvmpipe (LLVM)")
        self.assertEqual(result["device_type"], "PHYSICAL_DEVICE_TYPE_CPU")

    def test_probe_missing_real_vulkaninfo_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = Path(root) / "lvp_icd.x86_64.json"
            manifest.write_text(json.dumps({"file_format_version": "1.0.0", "ICD":
                {"library_path": "libvulkan_lvp.so", "api_version": "1.3.0"}}), encoding="utf-8")
            with patch("software_gpu.drivers.vulkan_reference._resolve_system_library",
                       return_value=Path("/usr/lib/libvulkan_lvp.so")):
                with self.assertRaises(FileNotFoundError):
                    run_reference_probe(manifest, vulkaninfo="/definitely/not/an/installed/vulkaninfo")

    def test_probe_loads_private_snapshot_with_absolute_library(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = Path(root) / "lvp_icd.json"
            manifest.write_text(json.dumps({"file_format_version": "1.0.0", "ICD":
                {"library_path": "libvulkan_lvp.so", "api_version": "1.3.0"}}), encoding="utf-8")
            resolved = Path("/usr/lib/libvulkan_lvp.so")

            def inspect_launch(*args, env, **kwargs):
                nonlocal snapshot
                snapshot = Path(env["VK_DRIVER_FILES"])
                manifest.unlink()
                self.assertNotEqual(snapshot, manifest)
                self.assertEqual(snapshot.parent.stat().st_mode & 0o077, 0)
                self.assertEqual(json.loads(snapshot.read_text())["ICD"]["library_path"], str(resolved))
                raise FileNotFoundError

            snapshot = None
            with patch("software_gpu.drivers.vulkan_reference._resolve_system_library", return_value=resolved), \
                    patch("software_gpu.drivers.vulkan_reference.subprocess.run", side_effect=inspect_launch):
                with self.assertRaises(FileNotFoundError):
                    run_reference_probe(manifest)
            self.assertIsNotNone(snapshot)
            self.assertFalse(snapshot.exists())


if __name__ == "__main__":
    unittest.main()
