"""Scheduler regression tests: five rejections are not a verified plateau."""
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[2] / ".github/workflows/scripts/autoloop_scheduler.py"
SPEC = importlib.util.spec_from_file_location("autoloop_scheduler", MODULE)
scheduler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scheduler)

class CpuAutoloopScheduleSafety(unittest.TestCase):
    def test_five_rejections_do_not_pause_without_complete_sweeps(self):
        skip, reason = scheduler.check_skip_conditions({
            "recent_statuses": ["rejected"] * 10, "paused": False, "completed": False})
        self.assertFalse(skip, reason)

    def test_three_full_sweeps_must_be_explicitly_verified_not_inferred(self):
        skip, reason = scheduler.check_skip_conditions({
            "recent_statuses": ["rejected"] * 18,
            "paused": True, "pause_reason": "verified: 3 complete gain-free catalog sweeps"})
        self.assertTrue(skip)
        self.assertIn("3 complete", reason)

    def test_error_pause_cannot_be_bypassed(self):
        skip, reason = scheduler.check_skip_conditions({
            "recent_statuses": ["error"] * 3, "paused": True,
            "pause_reason": "evaluation failed"})
        self.assertTrue(skip)
        self.assertIn("evaluation failed", reason)

    def test_no_cpu_ledger_cannot_start_autonomous_search(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "CPU_EVIDENCE_STATE_MISSING"):
                scheduler.certified_cpu_plateau("softwaregpu-cpu", tmp)

    def test_non_cpu_program_not_constrained_by_cpu_ledger(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(scheduler.certified_cpu_plateau("different-program", tmp))

    def test_completed_ignores_queued_runs(self):
        skip, reason = scheduler.check_skip_conditions({"completed": True})
        self.assertTrue(skip)
        self.assertIn("completed", reason)

if __name__ == "__main__":
    unittest.main()
