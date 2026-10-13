"""Fail-closed admission tests; no SSH, VPS mutation or benchmark process."""
import os
import sys
import unittest
from unittest.mock import patch

@unittest.skipUnless(sys.platform == "linux", "POSIX Linux VPS launcher")
class VPSBioAdmissionTests(unittest.TestCase):
    def setUp(self):
        from tools.vps_bio_host import GIB, admission
        self.GIB = GIB
        self.admission = admission
        self.good = {
            "affinity": list(range(8)),
            "logical_cpus": 8,
            "load_1m": 0.9,
            "load_5m": 1.0,
            "mem_available_bytes": 24*GIB,
            "disk_free_bytes": 60*GIB,
            "disk_used_fraction": 0.75,
        }

    def test_pilot_admits_quiet_host_only_and_selects_two_cpus(self):
        d=self.admission(dict(self.good), "pilot")
        self.assertEqual(d["status"],"GO")
        self.assertEqual(d["selected_cpus"],[0,1])
        self.assertEqual(d["limits"]["address_space_gib"],4)

    def test_current_host_disk_pressure_blocks_pilot(self):
        actual=dict(self.good,disk_used_fraction=0.888081,
                    disk_free_bytes=46564458496,load_1m=4.458)
        d=self.admission(actual,"pilot")
        self.assertEqual(d["status"],"STOP")
        self.assertIn("DISK_PRESSURE_HIGH",d["failures"])
        self.assertIn("CPU_LOAD_NOT_QUIET",d["failures"])

    def test_low_memory_disk_and_cpu_all_block(self):
        d=self.admission(dict(self.good,affinity=[0],
            mem_available_bytes=3*self.GIB,disk_free_bytes=2*self.GIB),"pilot")
        self.assertEqual(d["status"],"STOP")
        for name in ("CPU_AFFINITY_INSUFFICIENT","MEMORY_HEADROOM_LOW","DISK_FREE_LOW"):
            self.assertIn(name,d["failures"])

    def test_full_requires_all_eight_and_quiet_window(self):
        good=self.admission(dict(self.good),"full")
        self.assertEqual(good["status"],"GO")
        self.assertEqual(good["selected_cpus"],list(range(8)))
        d=self.admission(dict(self.good,affinity=[0,1,2,3]),"full")
        self.assertIn("CPU_AFFINITY_INSUFFICIENT",d["failures"])
        d=self.admission(dict(self.good,load_1m=2.4),"full")
        self.assertIn("CPU_LOAD_NOT_QUIET",d["failures"])

    def test_unknown_policy_rejected(self):
        with self.assertRaisesRegex(ValueError,"PROFILE_UNKNOWN"):
            self.admission(dict(self.good),"unbounded")

    def test_revision_guard_mismatch_prevents_host_run(self):
        from tools.vps_bio_host import verified_head, HostGateError
        with self.assertRaisesRegex(HostGateError,"EXPECTED_SHA_REQUIRED"):
            verified_head("main")
        with patch("tools.vps_bio_host.subprocess.check_output",
                   return_value="0"*40):
            with self.assertRaisesRegex(HostGateError,"SOURCE_SHA_MISMATCH"):
                verified_head("1"*40)

if __name__=="__main__":
    unittest.main()
