"""Container framing tests; fixtures are generated in-process and are NOT production assets."""
import json
import struct
import unittest

from tools.glb_container_preflight import inspect_glb


def glb(doc, binary=None):
    payload = json.dumps(doc, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    parts = [struct.pack("<II", len(payload), 0x4E4F534A) + payload]
    if binary is not None:
        binary += b"\x00" * (-len(binary) % 4)
        parts.append(struct.pack("<II", len(binary), 0x004E4942) + binary)
    body = b"".join(parts)
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


class GLBContainerPreflightTests(unittest.TestCase):
    def test_empty_morph_target_is_valid_container_metadata(self):
        doc = {"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"targets": [{}]}]}]}
        self.assertEqual(inspect_glb(glb(doc))["morph_targets"], 1)

    def test_embedded_buffer_exact_and_padded(self):
        doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 1}]}
        self.assertEqual(inspect_glb(glb(doc, b"x"))["bytes"], len(glb(doc, b"x")))

    def test_wrong_length_rejected(self):
        data = bytearray(glb({"asset": {"version": "2.0"}}))
        struct.pack_into("<I", data, 8, len(data) + 4)
        with self.assertRaises(ValueError):
            inspect_glb(data)

    def test_missing_bin_rejected(self):
        with self.assertRaises(ValueError):
            inspect_glb(glb({"asset": {"version": "2.0"}, "buffers": [{"byteLength": 5}]}))

    def test_declared_bin_length_rejected(self):
        with self.assertRaises(ValueError):
            inspect_glb(glb({"asset": {"version": "2.0"}, "buffers": [{"byteLength": 5}]}, b"x"))

    def test_truncated_json_rejected(self):
        with self.assertRaises(ValueError):
            inspect_glb(b"glTF" + struct.pack("<II", 2, 20) + b"\x00" * 8)

    def test_second_json_chunk_rejected(self):
        data = glb({"asset": {"version": "2.0"}})
        additional = struct.pack("<II", 4, 0x4E4F534A) + b"null"
        data = data[:8] + struct.pack("<I", len(data) + len(additional)) + data[12:] + additional
        with self.assertRaises(ValueError):
            inspect_glb(data)

    def test_malformed_asset_object_rejected_cleanly(self):
        with self.assertRaises(ValueError):
            inspect_glb(glb({"asset": "malformed"}))

    def test_non_array_meshes_rejected_cleanly(self):
        with self.assertRaises(ValueError):
            inspect_glb(glb({"asset": {"version": "2.0"}, "meshes": "not-an-array"}))

    def test_unreferenced_bin_chunk_rejected(self):
        with self.assertRaises(ValueError):
            inspect_glb(glb({"asset": {"version": "2.0"}}, b"data"))

    def test_padding_must_not_exceed_three_bytes(self):
        doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 0}]}
        with self.assertRaises(ValueError):
            inspect_glb(glb(doc, b"data"))


if __name__ == "__main__":
    unittest.main()
