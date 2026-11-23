"""Actual SPIR-V SSA negative tests; positive real shaders are built in CI."""
import struct
import unittest

from software_gpu.drivers.spirv_opcode_executor import RestrictedSpirvProgram, UnsupportedSpirv


def u32(*words):
    return struct.pack("<" + "I" * len(words), *words)


class TestRestrictedSpirvProgram(unittest.TestCase):
    def test_cannot_accept_header_or_unvalidated_module(self):
        for blob in (b"", u32(0x07230203, 0x00010500, 0, 8, 0),
                     u32(0x07230203, 0x00010500, 0, 8, 0, (1 << 16) | 9999)):
            with self.assertRaises(UnsupportedSpirv):
                RestrictedSpirvProgram._parse_validated_bytes(blob)

    def test_unknown_opcodes_cannot_execute(self):
        blob = u32(0x07230203, 0x00010500, 0, 8, 0,
                   (2 << 16) | 17, 1,
                   (1 << 16) | 9999)
        with self.assertRaisesRegex(UnsupportedSpirv, "OPCODE"):
            RestrictedSpirvProgram._parse_validated_bytes(blob)

    def test_structural_function_end_is_preserved_for_execution(self):
        # Structural-only test fixture, NOT a semantically validated shader.
        # The real positive gate separately runs glslang + spirv-val + ARE tiles.
        blob = u32(
            0x07230203, 0x00010500, 0, 8, 0,
            (2 << 16) | 17, 1,
            (3 << 16) | 14, 0, 1,
            (5 << 16) | 15, 0, 4, 1852399981, 0,
            (5 << 16) | 54, 2, 4, 0, 3,
            (2 << 16) | 248, 5,
            (1 << 16) | 253,
            (1 << 16) | 56,
        )
        program = RestrictedSpirvProgram._parse_validated_bytes(blob)
        self.assertEqual(program.steps[-2][0], 253)
        self.assertEqual(program.steps[-1][0], 56)
        self.assertFalse(program.validator["executed"])

    def test_programs_must_be_real_spirv_validated_files(self):
        with self.assertRaises(FileNotFoundError):
            RestrictedSpirvProgram.from_file(
                "/definitely/missing/compiled_shader.spv")

    def test_only_vertex_and_fragment_are_executable(self):
        # A structural word scanner is never enough to mark real execution.
        bad = u32(0x07230203, 0x00010500, 0, 8, 0, (1 << 16) | 253)
        with self.assertRaises(UnsupportedSpirv):
            RestrictedSpirvProgram._parse_validated_bytes(bad)


if __name__ == "__main__":
    unittest.main()
