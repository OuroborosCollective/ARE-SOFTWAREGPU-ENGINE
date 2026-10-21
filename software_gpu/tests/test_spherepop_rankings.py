"""Regression gates for historical CPU ranking sources, not timing mocks."""
import copy
import json
from pathlib import Path
import unittest
from software_gpu.benchmarks import spherepop_rankings as rank

class TestCpuWaveLeaderboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wave=json.loads(rank.WAVE.read_text(encoding="utf-8"))
        cls.window=json.loads(rank.WINDOW.read_text(encoding="utf-8"))

    def test_four_real_wave_scenes_and_four_impact_scenes(self):
        board=rank.assemble(self.wave,self.window)
        self.assertEqual(len(board["wave"]),4)
        self.assertEqual(len(board["impact"]),4)
        for case in board["wave"]:
            self.assertEqual(case["pairs"],15)
            self.assertEqual(case["ranks"][0]["backend"],"native-cpp")
            self.assertEqual(len(case["ranks"]),3)
        for case in board["impact"]:
            self.assertEqual(case["pairs"],15)
            self.assertEqual(case["ranks"][0]["mode"],"ring")
        self.assertIn("kein",rank.render(board).lower())

    def test_source_checksum_tamper_rejected(self):
        corrupt=copy.deepcopy(self.wave)
        corrupt["rows"][0]["modes"]["native-cpp"]["raw_ms"]["on"][0]*=20
        with self.assertRaisesRegex(ValueError,"RANKING_RECEIPT_SHA"):
            rank.assemble(corrupt,self.window)

    def test_consistently_rehashed_fabricated_median_rejected(self):
        corrupt=copy.deepcopy(self.wave)
        corrupt["rows"][0]["modes"]["native-cpp"]["raster_plus_wave"]["median"]=0.000001
        corrupt["sha256"]=rank.digest(corrupt)
        with self.assertRaisesRegex(ValueError,"RANKING_MEDIAN_DRIFT"):
            rank.assemble(corrupt,self.window)

    def test_frame_parity_gate(self):
        corrupt=copy.deepcopy(self.wave)
        corrupt["rows"][0]["effect"]["depth_sha256"]="0"*64
        corrupt["sha256"]=rank.digest(corrupt)
        with self.assertRaisesRegex(ValueError,"RANKING_FRAME_PARITY"):
            rank.assemble(corrupt,self.window)

    def test_empty_and_negative_samples_are_rejected(self):
        for timing in ([],[-1.0]*15):
            corrupt=copy.deepcopy(self.wave)
            corrupt["rows"][0]["modes"]["tiles"]["raw_ms"]["on"]=timing
            corrupt["sha256"]=rank.digest(corrupt)
            with self.assertRaisesRegex(ValueError,"RANKING_SAMPLE"):
                rank.assemble(corrupt,self.window)

    def test_impact_output_semantics_gate(self):
        corrupt=copy.deepcopy(self.window)
        corrupt["rows"][0]["static_rgba_fnv64"]=0
        with self.assertRaisesRegex(ValueError,"RANKING_WINDOW_PARITY"):
            rank.assemble(self.wave,corrupt)

    def test_documentation_canonical_snapshot(self):
        board=rank.assemble(self.wave,self.window)
        path=rank.ROOT/"docs/CPU_WAVE_RANGLISTEN.md"
        self.assertEqual(path.read_text(encoding="utf-8"),rank.render(board))

if __name__=="__main__":
    unittest.main()
