"""Post-vertex clip space through the real C++ raster and saved command weights."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from software_gpu.drivers.clip_draws import record_clip_draws
from software_gpu.drivers.command_submission import submit_native_draws
from software_gpu.drivers.native_bridge import AREDriverBridge, build_driver_bridge
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.learning import LocalLearner


class ClipDrawTests(unittest.TestCase):
    def test_negative_depth_and_far_plane(self):
        positions = np.array([[-1, -1, -.1, 1], [1, -1, -.1, 1], [-1, 1, -.1, 1]], np.float32)
        colors = np.ones((3, 3), np.float32)
        for depth in (-.1, 1.1):
            positions[:, 2] = depth
            packet = record_clip_draws([(positions, colors)], 16, 16)
            self.assertEqual(packet.commands[0].count, 0)
        positions[:, 2] = [-.25, .25, .25]
        cmd = record_clip_draws([(positions, colors)], 16, 16).commands[0]
        self.assertEqual(cmd.count, 2)
        depths = np.frombuffer(cmd.payload, np.float64).reshape(-1, 23)[:, [2, 5, 8]]
        self.assertEqual(depths.min(), 0.)
        self.assertEqual(depths.max(), .25)

    def test_submission_and_persisted_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary, build = build_driver_bridge(root)
            for repetitions in (4, 1):
                subprocess.run([sys.executable, "-m", "software_gpu.tests.test_clip_draws",
                                str(binary), build["binary_sha256"], str(root), str(repetitions)],
                               check=True, timeout=30)
            profile, = LocalLearner(root / "weights.sqlite3", create=False).status()
            self.assertEqual(profile["pairs"], 4)
            self.assertEqual(profile["runs"], 5)
            self.assertFalse(profile["blocked"])

    def _check_submission(self, root, bridge, repetitions):
        pos = np.array([[-1, -1, .5, 1], [1, -1, .5, 1], [-1, 1, .5, 1]], np.float32)
        red = np.tile(np.float32([1, 0, 0]), (3, 1))
        green = np.tile(np.float32([0, 1, 0]), (3, 1))
        packet = record_clip_draws([(pos, red), (pos[::-1], green)], 16, 16)
        store = root / "weights.sqlite3"
        with patch.dict(os.environ, {"ARE_LEARNING_DB": str(store)}):
            for _ in range(repetitions):
                frame = Framebuffer(16, 16)
                frame.clear()
                result = submit_native_draws(bridge, frame, packet)
                np.testing.assert_array_equal(frame.color_buffer[2, 2], [255, 0, 0, 255])
                self.assertEqual(frame.depth_buffer[2, 2], .5)
                self.assertEqual(frame.depth_buffer[14, 14], 1.)
                if repetitions == 4:
                    self.assertEqual(result["learning"]["outcome"], "matched")
                self.assertGreater(result["shaded_samples"], 0)


if __name__ == "__main__":
    binary, sha, root, repeats = sys.argv[1:]
    ClipDrawTests()._check_submission(Path(root), AREDriverBridge(binary, sha), int(repeats))
