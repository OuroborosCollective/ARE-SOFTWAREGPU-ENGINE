"""Pure sampler-create-info validation, not Vulkan runtime evidence.

The independent native sampler_probe.cpp uses the actual Khronos loader.
"""
import unittest
import sys

if sys.platform == "linux":
    import vulkan as vk
    from software_gpu.drivers.weighted_icd import Rejected, sampler_spec
    ffi = vk.ffi
else:
    # The ARE Vulkan ICD is built only for Linux, not the Windows CI runners.
    vk = ffi = None


def info():
    p = ffi.new("VkSamplerCreateInfo *")
    p.sType = vk.VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO
    p.magFilter = vk.VK_FILTER_NEAREST
    p.minFilter = vk.VK_FILTER_NEAREST
    p.mipmapMode = vk.VK_SAMPLER_MIPMAP_MODE_NEAREST
    p.addressModeU = p.addressModeV = p.addressModeW = vk.VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE
    p.maxAnisotropy = 1
    p.compareOp = vk.VK_COMPARE_OP_ALWAYS
    p.borderColor = vk.VK_BORDER_COLOR_FLOAT_TRANSPARENT_BLACK
    return p


@unittest.skipUnless(sys.platform == "linux", "Linux Vulkan ICD only")
class SamplerCreateInfoTests(unittest.TestCase):
    def test_supported_properties_form_immutable_snapshot(self):
        p = info()
        original = sampler_spec(p)
        self.assertEqual(original.mag_filter, vk.VK_FILTER_NEAREST)
        self.assertEqual(original.address_u, vk.VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE)
        p.magFilter = vk.VK_FILTER_LINEAR
        p.addressModeU = vk.VK_SAMPLER_ADDRESS_MODE_REPEAT
        next_one = sampler_spec(p)
        self.assertNotEqual(original, next_one)
        self.assertEqual(original.mag_filter, vk.VK_FILTER_NEAREST)

    def test_anisotropy_is_rejected_not_falsely_advertised(self):
        p = info()
        p.anisotropyEnable = vk.VK_TRUE
        p.maxAnisotropy = 8
        with self.assertRaises(Rejected):
            sampler_spec(p)

    def test_unknown_extension_chain_cannot_be_admitted(self):
        p = info()
        extension = ffi.new("uint32_t[1]", [123])
        p.pNext = extension
        with self.assertRaises(Rejected):
            sampler_spec(p)

    def test_extended_sampler_feature_flags_rejected(self):
        p = info()
        p.flags = 1
        with self.assertRaises(Rejected):
            sampler_spec(p)

    def test_invalid_filter_rejected(self):
        p = info()
        p.magFilter = 12345
        with self.assertRaises(Rejected):
            sampler_spec(p)

    def test_unimplemented_unnormalized_coordinates_rejected(self):
        p = info()
        p.unnormalizedCoordinates = 1
        with self.assertRaises(Rejected):
            sampler_spec(p)

    def test_invalid_lod_interval_rejected(self):
        p = info()
        p.minLod = 6
        p.maxLod = 1
        with self.assertRaises(Rejected):
            sampler_spec(p)

    def test_nonzero_lod_bias_exceeding_current_device_limit_rejected(self):
        p = info()
        p.mipLodBias = 0.5
        with self.assertRaises(Rejected):
            sampler_spec(p)
