"""Fail-closed interpretation only; real device evidence comes from native loader."""
import unittest
from software_gpu.drivers.verify_opengl_zink_preflight import classify


class TestZinkAdmissionContract(unittest.TestCase):
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
