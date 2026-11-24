"""Independent byte oracle for genuine VkCmdCopyBuffer output, no fake Vulkan."""
import hashlib
import tempfile
import unittest
from pathlib import Path


def expected_live_transfer():
    seeded = bytes((i*37+11)%256 for i in range(64))
    expected = bytearray(64)
    expected[12:32] = seeded[4:24]
    return bytes(expected)


def verify_transferred_bytes(path):
    actual = Path(path).read_bytes()
    expected = expected_live_transfer()
    if len(actual) != 64:
        raise ValueError("ARE_TRANSFER_BYTE_COUNT_MISMATCH")
    if actual != expected:
        raise ValueError("ARE_TRANSFER_NATIVE_REPLAY_BYTES_MISMATCH")
    return hashlib.sha256(actual).hexdigest()


class TestVulkanNativeBufferTransferOracle(unittest.TestCase):
    def test_exact_transfer_range_and_unmodified_tail(self):
        expected = expected_live_transfer()
        self.assertEqual(len(expected),64)
        self.assertEqual(expected[:12],bytes(12))
        self.assertEqual(expected[32:],bytes(32))
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "transfer.bin"
            file.write_bytes(expected)  # unit byte-oracle only; NOT runtime
            self.assertEqual(verify_transferred_bytes(file),
                             hashlib.sha256(expected).hexdigest())

    def test_changed_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "copy.bin"
            payload = bytearray(expected_live_transfer())
            payload[23] ^= 1
            file.write_bytes(payload)
            with self.assertRaisesRegex(ValueError,"ARE_TRANSFER_NATIVE_REPLAY_BYTES_MISMATCH"):
                verify_transferred_bytes(file)

    def test_truncated_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "copy.bin"
            file.write_bytes(expected_live_transfer()[:63])
            with self.assertRaisesRegex(ValueError,"ARE_TRANSFER_BYTE_COUNT_MISMATCH"):
                verify_transferred_bytes(file)
