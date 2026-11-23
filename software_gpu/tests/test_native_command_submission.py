"""Real native CPU submission queue: immutable commands and atomic failure."""
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np

from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.geometry import prepare_triangles
from software_gpu.graphics.native_raster import pack_triangles
from software_gpu.drivers.native_bridge import AREDriverBridge, build_driver_bridge
from software_gpu.drivers.command_submission import (
    record_native_draws, submit_native_draws,
)


class TestNativeCommandSubmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="are-command-")
        binary, receipt = build_driver_bridge(Path(cls.workspace.name))
        cls.bridge = AREDriverBridge(binary, receipt["binary_sha256"])
        mesh, faces = make_fixture(4, 0.8)
        cls.packed = pack_triangles(
            prepare_triangles(mesh, faces, VertexColorShader(), 32, 24))
        if cls.packed.shape[0] == 0:
            raise AssertionError("real triangle input is required")

    @classmethod
    def tearDownClass(cls):
        import sys
        if sys.platform == "win32":
            cls.workspace._finalizer.detach()
        else:
            cls.workspace.cleanup()

    def framebuffer(self):
        frame = Framebuffer(32, 24)
        frame.clear()
        return frame

    def test_real_native_draw_two_commands_and_replay(self):
        submitted = record_native_draws([self.packed.copy(), self.packed.copy()])
        actual = self.framebuffer()
        expected = self.framebuffer()
        replay = self.framebuffer()
        receipt = submit_native_draws(self.bridge, actual, submitted)
        self.bridge.draw_packed(expected, self.packed)
        self.bridge.draw_packed(expected, self.packed)
        again = submit_native_draws(self.bridge, replay, submitted)
        self.assertEqual(actual.color_buffer.tobytes(), expected.color_buffer.tobytes())
        self.assertEqual(actual.depth_buffer.tobytes(), expected.depth_buffer.tobytes())
        self.assertEqual(actual.color_buffer.tobytes(), replay.color_buffer.tobytes())
        self.assertEqual(actual.depth_buffer.tobytes(), replay.depth_buffer.tobytes())
        self.assertEqual(receipt["rgba_sha256"], again["rgba_sha256"])
        self.assertEqual(receipt["depth_sha256"], again["depth_sha256"])
        self.assertEqual(receipt["submitted_draws"], 2)
        self.assertGreater(receipt["shaded_samples"], 0)
        self.assertFalse(receipt["vulkan_command_buffer"])
        self.assertEqual(receipt["protocol"], "are.native-command-submission.v1")

    def test_input_mutation_after_record_does_not_affect_render(self):
        first = self.packed.copy()
        packet = record_native_draws([first])
        first[:] = 0.0
        actual = self.framebuffer()
        expected = self.framebuffer()
        submit_native_draws(self.bridge, actual, packet)
        self.bridge.draw_packed(expected, self.packed)
        self.assertEqual(actual.color_buffer.tobytes(), expected.color_buffer.tobytes())
        self.assertEqual(actual.depth_buffer.tobytes(), expected.depth_buffer.tobytes())

    def test_second_invalid_draw_is_atomic_for_entire_submission(self):
        corrupt = self.packed.copy()
        corrupt[-1, 0] = np.nan
        packet = record_native_draws([self.packed, corrupt])
        frame = self.framebuffer()
        before = (frame.color_buffer.tobytes(), frame.depth_buffer.tobytes())
        with self.assertRaisesRegex(ValueError, "ARE_COMMAND_SUBMISSION_REJECTED"):
            submit_native_draws(self.bridge, frame, packet)
        self.assertEqual((frame.color_buffer.tobytes(), frame.depth_buffer.tobytes()), before)

    def test_original_packet_digest_must_match_and_reject_unknown_abi(self):
        packet = record_native_draws([self.packed])
        frame = self.framebuffer()
        from dataclasses import replace
        with self.assertRaises(AttributeError):
            packet.commands[0].payload = bytes(len(packet.commands[0].payload))
        forged_command = replace(packet.commands[0], payload=bytes(len(packet.commands[0].payload)))
        forged_packet = replace(packet, commands=(forged_command,))
        before = (frame.color_buffer.tobytes(), frame.depth_buffer.tobytes())
        with self.assertRaisesRegex(ValueError, "ARE_COMMAND_PAYLOAD_DIGEST"):
            submit_native_draws(self.bridge, frame, forged_packet)
        self.assertEqual((frame.color_buffer.tobytes(), frame.depth_buffer.tobytes()), before)
        with self.assertRaisesRegex(ValueError, "ARE_COMMAND_PROFILE"):
            record_native_draws([self.packed], profile="spirv-vulkan")

    def test_packet_budgets_and_bad_buffers(self):
        with self.assertRaisesRegex(ValueError, "ARE_COMMAND_BUDGET"):
            record_native_draws([self.packed] * 257)
        with self.assertRaisesRegex(ValueError, "ARE_COMMAND_PACKED"):
            record_native_draws([np.zeros((1, 23), dtype=np.float32)])
        with self.assertRaisesRegex(ValueError, "ARE_COMMAND_PACKED"):
            record_native_draws([np.zeros((1, 24), dtype=np.float64)])

    def test_rejects_invalid_output_frame_without_effect(self):
        packet = record_native_draws([self.packed])
        frame = self.framebuffer()
        before = (frame.color_buffer.tobytes(), frame.depth_buffer.tobytes())
        frame.depth_buffer.flags.writeable = False
        try:
            with self.assertRaisesRegex(ValueError, "ARE_COMMAND_FRAME"):
                submit_native_draws(self.bridge, frame, packet)
        finally:
            frame.depth_buffer.flags.writeable = True
        self.assertEqual((frame.color_buffer.tobytes(), frame.depth_buffer.tobytes()), before)


if __name__ == "__main__":
    unittest.main()
