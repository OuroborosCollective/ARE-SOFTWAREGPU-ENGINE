"""Plateau is three complete, independently accepted/rejected sweeps, not 5 failures."""
import unittest
from software_gpu.benchmarks.autoloop_plateau import verify

CAT={"protocol":"are.autoloop-cpu-catalog.v1","candidates":["a","b"],"scenes":["tiny"],"pixels":[64,128],"workers":[1]}
def attempts(n=3):
    return [{"sweep":s,"candidate":c,"scene":"tiny","pixels":p,"workers":1,
             "status":"rejected","ci_verified":True,"receipt_sha256":"f"*64}
            for s in range(1,n+1) for c in ("a","b") for p in (64,128)]

class TestPlateau(unittest.TestCase):
    def test_three_full_rejected_sweeps_complete(self):
        self.assertTrue(verify(CAT,attempts())["completed"])
    def test_two_sweeps_not_enough(self):
        self.assertFalse(verify(CAT,attempts(2))["completed"])
    def test_missing_profile_does_not_count(self):
        self.assertFalse(verify(CAT,attempts()[:-1])["completed"])
    def test_accepted_candidate_resets_streak(self):
        x=attempts()
        x[6]["status"]="accepted"
        self.assertFalse(verify(CAT,x)["completed"])
    def test_failed_or_unverified_not_counted(self):
        x=attempts()
        x[-1]["status"]="error"
        self.assertFalse(verify(CAT,x)["completed"])
        x=attempts()
        x[-1]["ci_verified"]=False
        with self.assertRaisesRegex(ValueError,"UNVERIFIED"):
            verify(CAT,x)
    def test_duplicate_and_unknown_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            verify(CAT,attempts()+[attempts()[0]])
        x=attempts()
        x[0]["candidate"]="unknown"
        with self.assertRaisesRegex(ValueError,"UNKNOWN"):
            verify(CAT,x)
