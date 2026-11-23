"""SPIR-V P0 source admission tests: no simulated shader execution."""
import struct
from pathlib import Path
import tempfile
import unittest

from software_gpu.drivers.spirv_admission import (
    parse_spirv_module, validate_spirv_module,
)


class SPIRVAdmissionTests(unittest.TestCase):
    @staticmethod
    def words(*items):
        return struct.pack("<" + "I" * len(items), *items)

    def test_invalid_header_and_truncated_instruction_fail_closed(self):
        for data in (
            b"", b"SPIRV", self.words(0x07230203, 0x00010600, 0, 5, 0),
            self.words(0x07230203, 0x00010600, 0, 5, 0, 0),
            self.words(0x07230203, 0x00010600, 0, 5, 0, 0x00040011, 1),
            self.words(0x03022307, 0x00010600, 0, 5, 0),
            self.words(0x07230203, 0x00010600, 0, 0, 0, 0x00020011, 1),
            self.words(0x07230203, 0x00020700, 0, 5, 0, 0x00020011, 1),
        ):
            with self.subTest(data=data[:20].hex()), self.assertRaises(ValueError):
                parse_spirv_module(data)

    def test_structural_parse_is_never_driver_shader_execution(self):
        # Synthetic structural probe is a negative test only, NOT runtime evidence.
        header = self.words(0x07230203, 0x00010000, 0, 10, 0)
        caps = self.words((2 << 16) | 17, 1)
        memory = self.words((3 << 16) | 14, 0, 1)
        entry = self.words((5 << 16) | 15, 0, 3, 0x6e69616d, 0)
        result = parse_spirv_module(header + caps + memory + entry)
        self.assertEqual(result["stages"], ["vertex"])
        self.assertEqual(result["capabilities"], [1])
        self.assertFalse(result["spirv_validation_executed"])
        self.assertFalse(result["are_shader_executed"])
        self.assertFalse(result["are_vkphysicaldevice_exposed"])

    def test_multiple_memory_models_duplicate_entry_and_unsupported_cap_fail(self):
        header = self.words(0x07230203, 0x00010000, 0, 10, 0)
        caps = self.words((2 << 16) | 17, 1)
        bad_cap = self.words((2 << 16) | 17, 5348)
        memory = self.words((3 << 16) | 14, 0, 1)
        entry = self.words((5 << 16) | 15, 0, 3, 0x6e69616d, 0)
        for payload in (caps + bad_cap + memory + entry,
                        caps + memory + memory + entry,
                        caps + memory + entry + entry,
                        caps + memory + self.words((4 << 16) | 15, 9, 3, 0)):
            with self.assertRaises(ValueError):
                parse_spirv_module(header + payload)

    def test_valid_spirv_13_header_is_parsed_without_claiming_execution(self):
        header = self.words(0x07230203, 0x00010300, 0, 10, 0)
        caps = self.words((2 << 16) | 17, 1)
        memory = self.words((3 << 16) | 14, 0, 1)
        entry = self.words((5 << 16) | 15, 4, 3, 0x6e69616d, 0)
        # Fragment shader entry-point is still only structurally inspected.
        actual = parse_spirv_module(header + caps + memory + entry)
        self.assertEqual(actual["spirv_version"], "1.3")
        self.assertEqual(actual["stages"], ["fragment"])
        self.assertFalse(actual["spirv_validation_executed"])
        self.assertFalse(actual["are_shader_executed"])

    def test_validator_absent_cannot_create_receipt(self):
        header = self.words(0x07230203, 0x00010000, 0, 10, 0)
        sample = header + self.words((2 << 16) | 17, 1) + (
            self.words((3 << 16) | 14, 0, 1)) + (
            self.words((5 << 16) | 15, 0, 3, 0x6e69616d, 0))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vertex.spv"
            path.write_bytes(sample)
            with self.assertRaises(FileNotFoundError):
                validate_spirv_module(path, validator="/not/a/real/spirv-val")


if __name__ == "__main__":
    unittest.main()
