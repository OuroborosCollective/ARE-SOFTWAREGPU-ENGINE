"""CI gate: coverage floors for the rendering core, enforced inside the suite.

Runs tools/coverage_gate.py as a subprocess; that tool re-runs the whole suite
under sys.monitoring and fails when any floor in it is violated. The inner run
sets COVERAGE_GATE_INNER so this test skips itself there (no recursion).

Needs Python >= 3.12 (sys.monitoring); older CI lanes skip. This keeps the
gate working without any workflow-file change, on every lane that can run it.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestCoverageGate(unittest.TestCase):
    @unittest.skipUnless(sys.version_info >= (3, 12), "sys.monitoring requires Python 3.12")
    @unittest.skipIf(os.environ.get("COVERAGE_GATE_INNER") == "1",
                     "inner monitored run: gate must not recurse")
    def test_coverage_floors_hold(self):
        env = dict(os.environ, COVERAGE_GATE_INNER="1")
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "coverage_gate.py")],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
            timeout=900)
        self.assertEqual(
            proc.returncode, 0,
            "coverage gate failed:\n" + proc.stdout[-4000:] + "\n" + proc.stderr[-1000:])

    def test_coverage_gate_detects_missing_coverage(self):
        # Negative control: floor evaluation must report violations, without
        # re-running the whole suite (pure function on synthetic data).
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "coverage_gate", str(REPO_ROOT / "tools" / "coverage_gate.py"))
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        failures = gate.evaluate({"software_gpu/graphics/framebuffer.py": 10.0}, 5.0)
        self.assertTrue(any("framebuffer.py" in f and "< floor" in f for f in failures))
        self.assertTrue(any(f.startswith("OVERALL") for f in failures))
        self.assertTrue(any("missing from measurement" in f for f in failures))
        self.assertEqual(gate.evaluate({rel: 100.0 for rel in gate.FLOORS}, 100.0), [])


if __name__ == "__main__":
    unittest.main()
