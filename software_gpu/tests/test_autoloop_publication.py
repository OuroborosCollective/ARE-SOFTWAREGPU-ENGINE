"""Contract-only tests with synthetic values, never CPU performance evidence."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from software_gpu.benchmarks import autoloop_publication as pub

SOURCE = "1" * 40
BASE = "2" * 40
URL = "https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/424242"

def ci():
    return {"id": 424242, "repository": {"full_name": pub.REPOSITORY},
            "head_sha": SOURCE, "status": "completed", "conclusion": "success",
            "event": "pull_request"}

class PublicationContract(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        hashes = {}
        for name in pub.REQUIRED_SOURCES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture for contract test " + name, encoding="utf-8")
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        profiles = []
        for scene in pub.SCENES:
            for pixels in pub.RESOLUTIONS:
                for workers in pub.WORKERS:
                    rounds = []
                    for round_id in range(2):
                        pairs = []
                        for i in range(15):
                            first = "baseline" if (i + round_id) % 2 == 0 else "candidate"
                            pairs.append({"order": [first, "candidate" if first == "baseline" else "baseline"],
                                          "baseline_ms": 10.0, "candidate_ms": 9.0})
                        rounds.append({"pairs": pairs})
                    profiles.append({"scene": scene, "pixels": pixels, "workers": workers,
                                     "baseline_rgba_sha256": "a"*64, "candidate_rgba_sha256": "a"*64,
                                     "baseline_depth_sha256": "b"*64, "candidate_depth_sha256": "b"*64,
                                     "rounds": rounds})
        self.receipt = {
            "protocol": pub.RECEIPT_PROTOCOL, "sequence": 1, "source_commit": SOURCE,
            "baseline_commit": BASE, "ci_url": URL,
            "render_scope": "whole-draw CPU RGBA8 plus float32 depth",
            "environment": {"runner": "ubuntu-24.04", "cpu": "CI only test fixture",
                            "python": "3.12", "numpy": "2.3", "workers": [1, 2]},
            "source_sha256": hashes, "profiles": profiles,
        }
        self.seal()

    def seal(self):
        self.receipt["sha256"] = pub.digest(self.receipt)

    def check(self, c=None):
        return pub.validate_receipt(self.receipt, self.root, ci() if c is None else c)

    def test_all_20_profiles_have_30_samples_and_parity(self):
        entries = self.check()
        self.assertEqual(len(entries), 20)
        self.assertTrue(all(e["samples"] == 30 and e["image_parity"] for e in entries))
        self.assertAlmostEqual(entries[0]["speedup"], 10/9)

    def test_website_board_matches_schema_and_empty_is_honest(self):
        board = pub.build_board([self.receipt], self.root, lambda _: ci())
        self.assertEqual(board["protocol"], "are.autoloop-public-leaderboard.v1")
        self.assertEqual(len(board["entries"]), 20)
        self.assertEqual(pub.build_board([], self.root, lambda _: self.fail("unexpected CI")), {
            "protocol": pub.BOARD_PROTOCOL, "scope": board["scope"], "sources": [], "entries": []})

    def test_edited_receipt_digest_is_rejected(self):
        self.receipt["profiles"][0]["rounds"][0]["pairs"][0]["candidate_ms"] = 0.01
        with self.assertRaisesRegex(ValueError, "RECEIPT_SHA"):
            self.check()

    def test_missing_profile_rejected(self):
        self.receipt["profiles"].pop()
        self.seal()
        with self.assertRaisesRegex(ValueError, "PROFILE_COVERAGE"):
            self.check()

    def test_bad_depth_sha_rejected(self):
        self.receipt["profiles"][0]["candidate_depth_sha256"] = "c"*64
        self.seal()
        with self.assertRaisesRegex(ValueError, "FRAME_PARITY"):
            self.check()

    def test_failed_ci_rejected(self):
        record = ci()
        record["conclusion"] = "failure"
        with self.assertRaisesRegex(ValueError, "CI_NOT_GREEN"):
            self.check(record)

    def test_wrong_source_revision_rejected(self):
        record = ci()
        record["head_sha"] = BASE
        with self.assertRaisesRegex(ValueError, "CI_HEAD"):
            self.check(record)

    def test_drifted_source_rejected(self):
        (self.root / pub.REQUIRED_SOURCES[0]).write_text("different", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SOURCE_DRIFT"):
            self.check()

    def test_too_small_gain_rejected(self):
        for row in self.receipt["profiles"]:
            for rnd in row["rounds"]:
                for pair in rnd["pairs"]:
                    pair["candidate_ms"] = 9.95
        self.seal()
        with self.assertRaisesRegex(ValueError, "GAIN_BELOW_THRESHOLD"):
            self.check()

    def test_regressed_profile_rejected(self):
        for rnd in self.receipt["profiles"][0]["rounds"]:
            for pair in rnd["pairs"]:
                pair["candidate_ms"] = 11.0
        self.seal()
        with self.assertRaisesRegex(ValueError, "PROFILE_REGRESSION"):
            self.check()

    def test_three_complete_no_gain_sweeps(self):
        catalog = ["allocation", "dispatch"]
        profiles = ["64", "128"]
        attempts = [
            {"sweep": n, "candidate": c, "profile": p, "status": "rejected"}
            for n in (1,2,3) for c in catalog for p in profiles
        ]
        self.assertTrue(pub.plateau_state(attempts, catalog, profiles)["completed"])
        attempts.pop()
        self.assertFalse(pub.plateau_state(attempts, catalog, profiles)["completed"])

    def test_error_cannot_count_as_plateau(self):
        attempts = [{"sweep": n, "candidate": "allocation", "profile": "64",
                     "status": "error" if n == 3 else "rejected"} for n in (1,2,3)]
        self.assertFalse(pub.plateau_state(attempts, ["allocation"], ["64"])["completed"])

if __name__ == "__main__":
    unittest.main()
