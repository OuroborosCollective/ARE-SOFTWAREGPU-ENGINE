"""Fail-closed interpretation only; real device evidence comes from native loader."""
import unittest
import json
import subprocess
import tempfile
from pathlib import Path
from software_gpu.drivers.verify_opengl_zink_preflight import classify, verify, digest


class TestZinkAdmissionContract(unittest.TestCase):
    def test_native_probe_includes_stdint_header_directly(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[2] / "native" / "vulkan" /
                  "weighted" / "opengl_zink_capability_probe.cpp").read_text()
        # Ubuntu 24.04 does not inherit std::uint32_t from Vulkan includes.
        self.assertIn("#include <cstdint>", source)

    def test_reported_missing_caps_refuse_opengl(self):
        observed = {
            "protocol": "are.zink-capability-preflight.v1",
            "device": "ARE SoftwareGPU (real Vulkan device)",
            "api_version": {"major":1, "minor":0},
            "max_bound_descriptor_sets":0,
            "extensions_advertised":["VK_KHR_swapchain"],
            "missing_gl21_features":["logicOp"],
            "missing_gl21_extensions":["VK_KHR_maintenance1"],
            "minimum_gl21_ready":False,
            "gl45_and_heaven_verified":False,
        }
        self.assertEqual(classify(3, observed), "incompatible")

    def test_unexpected_crash_is_never_a_valid_incompatibility_receipt(self):
        with self.assertRaises(ValueError):
            classify(139, {"protocol":"are.zink-capability-preflight.v1"})

    def test_non_are_identity_is_rejected(self):
        observed = {"protocol":"are.zink-capability-preflight.v1",
                    "device":"llvmpipe (LLVM)"}
        with self.assertRaises(ValueError):
            classify(3, observed)

    def test_claimed_ready_cannot_contain_missing_features(self):
        observed = {"protocol":"are.zink-capability-preflight.v1",
                    "device":"ARE SoftwareGPU",
                    "minimum_gl21_ready":True,
                    "missing_gl21_features":["logicOp"],
                    "missing_gl21_extensions":[]}
        with self.assertRaises(ValueError):
            classify(0, observed)

    def test_missing_capabilities_without_failure_cannot_pass(self):
        observed = {"protocol":"are.zink-capability-preflight.v1",
                    "device":"ARE SoftwareGPU",
                    "minimum_gl21_ready":False,
                    "missing_gl21_features":["logicOp"],
                    "missing_gl21_extensions":[]}
        with self.assertRaises(ValueError):
            classify(0, observed)

    def _data_contract(self):
        # Unit-only schema values, explicitly NOT a real Vulkan runtime.
        return {"protocol": "are.zink-capability-preflight.v1",
                "device": "ARE SoftwareGPU (unit-data-only)",
                "gl45_and_heaven_verified": False,
                "api_version": {"major": 1, "minor": 0},
                "extensions_advertised": ["VK_KHR_swapchain"],
                "missing_gl21_features": ["logicOp"],
                "missing_gl21_extensions": ["VK_KHR_maintenance1"],
                "minimum_gl21_ready": False}

    def test_revision_rejects_non_sha_without_creating_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "reject"
            with self.assertRaisesRegex(ValueError, "ARE_ZINK_SOURCE_REVISION_MISMATCH"):
                verify(out, Path(td) / "no-manifest", "not-a-full-sha",
                       Path(td) / "no-headers")
            self.assertFalse(out.exists())

    def test_revision_rejects_different_real_shape_sha(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(__file__).resolve().parents[2]
            head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                           cwd=repo, text=True).strip()
            wrong = ("0" if head[0] != "0" else "1") + head[1:]
            out = Path(td) / "reject"
            with self.assertRaisesRegex(ValueError, "ARE_ZINK_SOURCE_REVISION_MISMATCH"):
                verify(out, Path(td) / "no-manifest", wrong, Path(td))
            self.assertFalse(out.exists())

    def test_missing_icd_manifest_fails_before_output_creation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(__file__).resolve().parents[2]
            head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                           cwd=repo, text=True).strip()
            out = Path(td) / "reject"
            with self.assertRaises(FileNotFoundError):
                verify(out, Path(td) / "missing-are.json", head, Path(td))
            self.assertFalse(out.exists())

    def test_malformed_icd_json_rejected_without_diagnostic_success(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(__file__).resolve().parents[2]
            head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                           cwd=repo, text=True).strip()
            manifest = Path(td) / "bad.json"
            manifest.write_text("{", encoding="utf8")
            out = Path(td) / "reject"
            with self.assertRaises(json.JSONDecodeError):
                verify(out, manifest, head, Path(td))
            self.assertFalse(out.exists())

    def test_missing_bound_driver_refused_before_compilation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(__file__).resolve().parents[2]
            head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                           cwd=repo, text=True).strip()
            manifest = Path(td) / "manifest.json"
            manifest.write_text(json.dumps(
                {"ICD": {"library_path": str(Path(td) / "absent.so"),
                         "api_version": "1.0.0"}}), encoding="utf8")
            out = Path(td) / "reject"
            with self.assertRaises(FileNotFoundError):
                verify(out, manifest, head, Path(td))
            self.assertFalse(out.exists())

    def test_non_are_named_file_refused_without_loading_library(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(__file__).resolve().parents[2]
            head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                           cwd=repo, text=True).strip()
            # Invalid negative-control bytes; never loaded as a Vulkan runtime.
            bad_library = Path(td) / "different-driver.so"
            bad_library.write_bytes(b"not-a-driver")
            manifest = Path(td) / "manifest.json"
            manifest.write_text(json.dumps({"ICD": {"library_path": str(bad_library),
                                                    "api_version": "1.0.0"}}),
                                encoding="utf8")
            out = Path(td) / "reject"
            with self.assertRaisesRegex(ValueError, "ARE_ZINK_ICD_LIBRARY_IDENTITY_INVALID"):
                verify(out, manifest, head, Path(td))
            self.assertFalse(out.exists())

    def test_unsupported_manifest_api_rejected_before_native_invocation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(__file__).resolve().parents[2]
            head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                           cwd=repo, text=True).strip()
            invalid = Path(td) / "libare_weighted.so"
            invalid.write_bytes(b"not-a-driver")
            manifest = Path(td) / "manifest.json"
            manifest.write_text(json.dumps(
                {"ICD": {"library_path": str(invalid), "api_version": "1.2.0"}}),
                encoding="utf8")
            with self.assertRaisesRegex(ValueError, "ARE_ZINK_ICD_PROFILE_MISMATCH"):
                verify(Path(td) / "not-created", manifest, head, Path(td))
            self.assertFalse((Path(td) / "not-created").exists())

    def test_existing_evidence_directory_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(__file__).resolve().parents[2]
            head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                           cwd=repo, text=True).strip()
            invalid = Path(td) / "libare_weighted.so"
            invalid.write_bytes(b"not-a-driver")
            manifest = Path(td) / "manifest.json"
            manifest.write_text(json.dumps(
                {"ICD": {"library_path": str(invalid), "api_version": "1.0.0"}}),
                encoding="utf8")
            out = Path(td) / "already-used"
            out.mkdir()
            original = out / "receipt.json"
            original.write_bytes(b"immutable-previous-receipt")
            with self.assertRaisesRegex(ValueError, "ARE_ZINK_OUTPUT_MUST_BE_EMPTY"):
                verify(out, manifest, head, Path(td))
            self.assertEqual(original.read_bytes(), b"immutable-previous-receipt")

    def test_driver_source_sha_changes_when_real_bytes_change(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "source"
            p.write_bytes(b"revision-a")
            before = digest(p)
            p.write_bytes(b"revision-b")
            self.assertNotEqual(digest(p), before)

    def test_invalid_capability_array_is_not_a_device_success(self):
        rec = self._data_contract()
        rec["missing_gl21_features"] = "logicOp"
        with self.assertRaisesRegex(ValueError, "ARE_ZINK_CAPABILITY_ARRAYS_INVALID"):
            classify(3, rec)

    def test_no_real_swapchain_is_never_accepted(self):
        rec = self._data_contract()
        rec["extensions_advertised"] = []
        with self.assertRaisesRegex(ValueError, "ARE_ZINK_ACTUAL_SWAPCHAIN_REQUIRED"):
            classify(3, rec)

    def test_forged_vulkan_api_major_is_rejected(self):
        rec = self._data_contract()
        rec["api_version"] = {"major": 2, "minor": 0}
        with self.assertRaisesRegex(ValueError, "ARE_ZINK_UNKNOWN_VULKAN_API"):
            classify(3, rec)

    def test_heaven_verified_claim_is_never_in_native_capability_probe(self):
        rec = self._data_contract()
        rec["gl45_and_heaven_verified"] = True
        with self.assertRaisesRegex(ValueError, "ARE_ZINK_NO_HEAVEN_RENDER_PROVEN"):
            classify(3, rec)

    def test_contradictory_success_without_missing_caps_is_rejected(self):
        rec = self._data_contract()
        rec["missing_gl21_features"] = []
        rec["missing_gl21_extensions"] = []
        with self.assertRaisesRegex(ValueError, "ARE_ZINK_PROBE_STATUS_CAPABILITIES_CONTRADICTION"):
            classify(3, rec)

    def test_nonruntime_schema_transition_only(self):
        # This is a data-parser contract, NOT proof that real ARE supports Zink.
        rec = self._data_contract()
        rec["minimum_gl21_ready"] = True
        rec["missing_gl21_features"] = []
        rec["missing_gl21_extensions"] = []
        self.assertEqual(classify(0, rec), "minimum-vulkan-capabilities")
