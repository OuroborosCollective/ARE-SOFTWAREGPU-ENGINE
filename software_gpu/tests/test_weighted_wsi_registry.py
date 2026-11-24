"""Validate cross-distribution Vulkan registry ABI normalization, not a fake ICD."""
import unittest
import xml.etree.ElementTree as ET

from software_gpu.drivers.build_weighted_icd import canonical_registry_params


def param(type_name, name):
    return ET.fromstring("<param>const <type>" + type_name + "</type>* <name>" +
                         name + "</name></param>")


class TestRegistryAbi(unittest.TestCase):
    def test_exact_ubuntu_duplicate_preserves_single_canonical_parameter(self):
        arguments = [param("VkDevice", "device"), param("VkSwapchainCreateInfoKHR", "pCreateInfo"),
                     param("VkSwapchainCreateInfoKHR", "pCreateInfo"),
                     param("VkAllocationCallbacks", "pAllocator"),
                     param("VkSwapchainKHR", "pSwapchain")]
        result = canonical_registry_params("vkCreateSwapchainKHR", arguments)
        self.assertEqual([q.findtext("name") for q in result],
                         ["device","pCreateInfo","pAllocator","pSwapchain"])

    def test_other_abi_ambiguity_fails_closed(self):
        params = [param("VkDevice","device"), param("VkDevice","device")]
        with self.assertRaisesRegex(ValueError,"DUPLICATE_ABI_ARGUMENT"):
            canonical_registry_params("vkCreateDevice", params)
        params = [param("VkDevice","device"),
                  param("VkSwapchainCreateInfoKHR","pCreateInfo"),
                  param("VkImageCreateInfo","pCreateInfo"),
                  param("VkAllocationCallbacks","pAllocator"),
                  param("VkSwapchainKHR","pSwapchain")]
        with self.assertRaisesRegex(ValueError,"CONFLICTING_SWAPCHAIN_ABI"):
            canonical_registry_params("vkCreateSwapchainKHR", params)

    def test_normal_api_metadata_unchanged(self):
        values = [param("VkDevice","device"),param("VkSwapchainCreateInfoKHR","pCreateInfo"),
                  param("VkAllocationCallbacks","pAllocator"),param("VkSwapchainKHR","pSwapchain")]
        self.assertEqual(canonical_registry_params("vkCreateSwapchainKHR", values), values)
