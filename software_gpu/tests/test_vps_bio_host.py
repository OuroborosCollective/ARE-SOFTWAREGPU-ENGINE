"""Shared Sovereign/Aurion benchmark host gate: no actual VPS or mocks of frames."""
from pathlib import Path
import unittest
from unittest import mock

from tools import vps_bio_host as host


def metrics(**changes):
    m = dict(affinity=list(range(8)), logical_cpus=8, load_1m=0.8, load_5m=0.6,
             mem_available_bytes=24 * host.GIB, disk_total_bytes=400*host.GIB,
             disk_free_bytes=80*host.GIB, disk_used_fraction=0.8)
    m.update(changes)
    return m


class TestSharedHostResourceGate(unittest.TestCase):
    def test_pilot_is_two_cpus_even_on_eight_core_host(self):
        result = host.admission(metrics(), "pilot")
        self.assertEqual(result["status"], "GO")
        self.assertEqual(result["selected_cpus"], [0, 1])
        self.assertEqual(result["limits"]["address_space_gib"], 4)

    def test_real_shared_vps_disk_pressure_fails_both_profiles(self):
        real = metrics(load_1m=4.458, disk_used_fraction=0.888081,
                       disk_free_bytes=46_564_458_496,
                       mem_available_bytes=24_099_860_480)
        for variant in ("pilot", "full"):
            with self.subTest(profile=variant):
                decision = host.admission(real, variant)
                self.assertEqual(decision["status"], "STOP")
                self.assertIn("DISK_PRESSURE_HIGH", decision["failures"])
        # Never automatically stop Sovereign/Aurion to free space.

    def test_load_memory_affinity_and_free_disk_fail_closed(self):
        cases = [
            (dict(affinity=[0]), "CPU_AFFINITY_INSUFFICIENT"),
            (dict(load_1m=7), "CPU_LOAD_NOT_QUIET"),
            (dict(mem_available_bytes=3 * host.GIB), "MEMORY_HEADROOM_LOW"),
            (dict(disk_free_bytes=2 * host.GIB), "DISK_FREE_LOW"),
            (dict(disk_used_fraction=.85), "DISK_PRESSURE_HIGH"),
        ]
        for change,expected in cases:
            with self.subTest(change=change):
                self.assertIn(expected,host.admission(metrics(**change),"pilot")["failures"])

    def test_full_sweep_requires_8_cpus_and_quiet_host(self):
        self.assertEqual(host.admission(metrics(),"full")["status"],"GO")
        self.assertIn("CPU_AFFINITY_INSUFFICIENT",
                      host.admission(metrics(affinity=list(range(7))),"full")["failures"])
        self.assertIn("CPU_LOAD_NOT_QUIET",
                      host.admission(metrics(load_1m=2),"full")["failures"])

    def test_sha_rejects_unpinned_or_dirty_git(self):
        for candidate in ("main", "abc", "A"*40, "0"*41):
            with self.subTest(candidate=candidate), self.assertRaisesRegex(
                    host.HostGateError, "EXPECTED_SHA_REQUIRED"):
                host.verified_head(candidate)
        with mock.patch("subprocess.check_output", side_effect=["a"*40, " M README.md"]):
            with self.assertRaisesRegex(host.HostGateError, "TRACKED_SOURCE_DIRTY"):
                host.verified_head("a"*40)

    def test_inspect_and_plan_do_not_create_directories(self):
        with mock.patch.object(host.os, "geteuid", return_value=1000, create=True), \
             mock.patch.object(host, "verified_head", return_value="b"*40), \
             mock.patch.object(host, "snapshot", return_value=metrics()), \
             mock.patch.object(Path, "mkdir", side_effect=AssertionError("unexpected write")):
            opt = mock.Mock(action="inspect", profile="pilot", expected_sha="b"*40,
                            output_base=Path.cwd() / "does-not-exist",
                            confirm_full_window=False)
            self.assertEqual(host.run(opt), 0)
            opt.action = "plan"
            self.assertEqual(host.run(opt), 0)
