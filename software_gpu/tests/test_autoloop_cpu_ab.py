"""Synthetic admission tests; never claim performance evidence from these values."""
import unittest
from software_gpu.benchmarks import autoloop_cpu_ab as ab

def make_profiles(before=10.0, after=9.0):
    rows = []
    for scene in ab.SCENES:
        for pixels in ab.RESOLUTIONS:
            for workers in ab.WORKERS:
                rounds = []
                for round_id in range(2):
                    pairs = []
                    for j in range(15):
                        first = "baseline" if (round_id+j) % 2 == 0 else "candidate"
                        pairs.append({"order": [first, "candidate" if first == "baseline" else "baseline"],
                                      "baseline_ms": before, "candidate_ms": after})
                    rounds.append({"pairs": pairs})
                rows.append({"scene": scene, "pixels": pixels, "workers": workers, "rounds": rounds,
                             "baseline_rgba_sha256": "a"*64, "candidate_rgba_sha256": "a"*64,
                             "baseline_depth_sha256": "b"*64, "candidate_depth_sha256": "b"*64})
    return rows

class TestEvidenceAdmission(unittest.TestCase):
    def test_twenty_profiles_and_thirty_pairs(self):
        result = ab.adjudicate(make_profiles())
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["profile_count"], 20)
        self.assertGreater(result["score"], 1.02)

    def test_no_gain_is_not_accepted(self):
        self.assertEqual(ab.adjudicate(make_profiles(10, 10))["outcome"], "no_gain")

    def test_one_bad_profile_blocks(self):
        rows = make_profiles()
        for rd in rows[0]["rounds"]:
            for pair in rd["pairs"]:
                pair["candidate_ms"] = 11.0
        self.assertEqual(ab.adjudicate(rows)["outcome"], "rejected")

    def test_incomplete_or_duplicate_profiles_block(self):
        with self.assertRaisesRegex(ValueError, "PROFILE_COVERAGE"):
            ab.adjudicate(make_profiles()[:-1])
        rows = make_profiles()
        rows[0] = rows[1]
        with self.assertRaisesRegex(ValueError, "PROFILE_COVERAGE"):
            ab.adjudicate(rows)

    def test_rgba_and_depth_hashes_block_mismatch(self):
        for key, reason in (("candidate_rgba_sha256", "RGBA_PARITY"), ("candidate_depth_sha256", "DEPTH_PARITY")):
            rows = make_profiles()
            rows[0][key] = "c"*64
            with self.assertRaisesRegex(ValueError, reason):
                ab.adjudicate(rows)

    def test_sample_count_and_order(self):
        rows = make_profiles()
        rows[0]["rounds"][0]["pairs"].pop()
        with self.assertRaisesRegex(ValueError, "PAIR_COVERAGE"):
            ab.adjudicate(rows)
        rows = make_profiles()
        rows[0]["rounds"][0]["pairs"][1]["order"] = ["baseline", "candidate"]
        with self.assertRaisesRegex(ValueError, "PAIR_ORDER"):
            ab.adjudicate(rows)

    def test_nan_bool_negative_zero_rejected(self):
        for bad in (0, -1, float("nan"), True):
            rows = make_profiles()
            rows[0]["rounds"][0]["pairs"][0]["baseline_ms"] = bad
            with self.assertRaisesRegex(ValueError, "PAIR_TIMING"):
                ab.adjudicate(rows)

    def test_source_scope(self):
        base = {name: "a"*64 for name in ab.SOURCE_PATHS}
        target = dict(base)
        target[ab.TARGET] = "c"*64
        ab.check_diff_scope(base, target)
        target["software_gpu/graphics/framebuffer.py"] = "d"*64
        with self.assertRaisesRegex(ValueError, "NON_TARGET_SOURCE_CHANGED"):
            ab.check_diff_scope(base, target)

if __name__ == "__main__":
    unittest.main()
