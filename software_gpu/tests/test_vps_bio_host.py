"""Shared Sovereign/Aurion VPS admission contracts; no VPS accessed in CI."""
import sys
import unittest

if sys.platform == "linux":
    from tools.vps_bio_host import GIB, HostGateError, PROFILES, admission


@unittest.skipUnless(sys.platform == "linux", "host admission only on Linux")
class TestSharedVpsBioGate(unittest.TestCase):
    def fixture(self):
        return dict(affinity=list(range(8)), mem_available_bytes=16*GIB,
                    disk_free_bytes=48*GIB, disk_used_fraction=.50, load_1m=.5)

    def test_bounded_two_cpu_pilot_and_full_eight_cpu_window(self):
        m=self.fixture()
        p=admission(m,"pilot")
        self.assertEqual(p["status"],"GO")
        self.assertEqual(p["selected_cpus"],[0,1])
        self.assertEqual(PROFILES["pilot"]["workers"],[1,2])
        f=admission(m,"full")
        self.assertEqual(f["status"],"GO")
        self.assertEqual(len(f["selected_cpus"]),8)

    def test_disk_p0_blocks_even_if_free_gb_high(self):
        m=self.fixture();m["disk_used_fraction"]=.888081
        for profile in ("pilot","full"):
            with self.subTest(profile=profile):
                p=admission(m,profile)
                self.assertEqual(p["status"],"STOP")
                self.assertIn("DISK_PRESSURE_HIGH",p["failures"])

    def test_live_host_cpu_load_blocks_pilot(self):
        m=self.fixture();m["load_1m"]=5.9
        self.assertIn("CPU_LOAD_NOT_QUIET",admission(m,"pilot")["failures"])

    def test_oversubscribed_host_blocks_full(self):
        m=self.fixture();m["affinity"]=[0,1]
        self.assertIn("CPU_AFFINITY_INSUFFICIENT",admission(m,"full")["failures"])

    def test_resource_exhaustion_fails_closed(self):
        m=self.fixture();m["disk_free_bytes"]=7*GIB
        m["mem_available_bytes"]=2*GIB
        p=admission(m,"pilot")
        self.assertIn("DISK_FREE_LOW",p["failures"])
        self.assertIn("MEMORY_HEADROOM_LOW",p["failures"])
        self.assertEqual(p["status"],"STOP")

    def test_unknown_profiles_rejected(self):
        with self.assertRaises(ValueError):
            admission(self.fixture(),"random")

    def test_limits_explicit_no_service_or_port_mutation(self):
        p=admission(self.fixture(),"pilot")
        self.assertTrue(p["limits"]["no_listening_ports"])
        self.assertEqual(p["limits"]["nice"],15)
        self.assertEqual(p["limits"]["address_space_gib"],4)


if __name__=="__main__":
    unittest.main()
