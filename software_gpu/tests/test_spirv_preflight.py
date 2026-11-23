"""Admission tests: actual SPIR-V tools are never replaced by a fake validator."""
import struct
import tempfile
import unittest
from pathlib import Path

from software_gpu.drivers.spirv_preflight import inspect_module, validate_module


def words(*values):
    return struct.pack("<" + "I" * len(values), *values)


class TestSpirvPreflight(unittest.TestCase):
    def test_bad_magic_and_short_header_fail_closed(self):
        for blob in (b"", b"SPV", words(1, 2, 3, 4, 5),
                     words(0x07230203, 0x00010600, 0, 64, 0) + b"x"):
            with self.assertRaises(ValueError):
                inspect_module(blob)

    def test_unsupported_version_bound_and_instruction_fail_closed(self):
        for blob in (
            words(0x07230203, 0x00010700, 0, 5, 0),
            words(0x07230203, 0x00010600, 0, 0, 0),
            words(0x07230203, 0x00010600, 0, 1_000_001, 0),
            words(0x07230203, 0x00010600, 0, 5, 0, (1 << 16) | 15),
            words(0x07230203, 0x00010600, 0, 5, 0, (0 << 16) | 15),
        ):
            with self.assertRaises(ValueError):
                inspect_module(blob)

    def test_header_alone_is_never_accepted_as_a_shader(self):
        blob = words(0x07230203, 0x00010600, 0, 5, 0)
        with self.assertRaises(ValueError):
            inspect_module(blob)

    def test_unavailable_real_validator_is_a_hard_failure(self):
        # Structured bytes are not valid SPIR-V modules. No inferred success
        # from header, even when the validator binary cannot be launched.
        with tempfile.TemporaryDirectory() as d:
            shader = Path(d) / "f.spv"
            shader.write_bytes(words(0x07230203, 0x00010600, 0, 5, 0))
            with self.assertRaises((FileNotFoundError, ValueError)):
                validate_module(shader, validator="/definitely/nonexistent/spirv-val")

    def test_nonexistent_shader_is_not_a_pass(self):
        with self.assertRaises(FileNotFoundError):
            validate_module(Path("/definitely/nonexistent/triangle.vert.spv"))


if __name__ == "__main__":
    unittest.main()
