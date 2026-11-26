"""Replay a recorded provider response and exercise the actual render and learning paths."""
import copy
from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from software_gpu.benchmarks.compare_cag_tone import compare
from software_gpu.graphics.cag_tone import CagToneShader
from software_gpu.research.cag_profile import parse_response, replay


PROVIDER = Path(__file__).resolve().parents[2] / "evidence/cag-smoothstep/provider.json"


class SmoothstepPilotTest(unittest.TestCase):
    def setUp(self):
        self.receipt = json.loads(PROVIDER.read_text())

    def test_all_levels_and_channel_order(self):
        table = replay(self.receipt)
        shader = CagToneShader(table)
        levels = np.arange(256, dtype=np.float32)
        colors = np.stack((levels, levels[::-1], np.roll(levels, 37)), axis=1) / 255
        batch = shader.fragment_shader_batch({"color": colors})
        for i in range(256):
            t = Fraction(i, 255)
            self.assertEqual(table[i], int(255 * t**2 * (3 - 2*t)))
            self.assertEqual(tuple(batch[i]), shader.fragment_shader({"color": colors[i]}))
        with self.assertRaises(ValueError):
            CagToneShader(bytes(256))

    def test_invalid_provider_and_replay(self):
        for key, value in (("result", "Failure[Timeout]"), ("result", "Out[1]= {1,2}"),
                           ("success", False), ("uuid", "invalid"), ("code", 403),
                           ("result", self.receipt["response"]["result"].replace("{0", "{1", 1))):
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_response(dict(self.receipt["response"], **{key: value}))
        for key in ("request_sha256", "response_sha256", "table_sha256", "endpoint"):
            row = copy.deepcopy(self.receipt)
            row[key] = "altered"
            with self.subTest(key=key), self.assertRaises(ValueError):
                replay(row)

    def test_local_learn_weight_and_held_out_depth(self):
        with TemporaryDirectory() as tmp:
            result = compare(self.receipt, Path(tmp) / "test.db", 64, 4)
        self.assertEqual(result["model_after_training"]["pairs"], 4)
        self.assertEqual(result["model_after_training"]["scope"]["variant"], "cag-smoothstep-batch-v1")
        self.assertEqual(result["cost"]["http_calls_during_render"], 0)
        for row in result["holdout"]:
            self.assertIn(row["served"], ("reference", "candidate"))
            for buf in row["buffers"].values():
                self.assertGreater(buf["covered_pixels"], 100)
                self.assertEqual(buf, row["buffers"]["scalar"])
