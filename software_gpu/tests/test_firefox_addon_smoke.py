"""Harness control-flow unit tests using explicit browser/process test doubles.

These tests never start Firefox or render pixels. Real-browser evidence is
produced separately by tools/firefox_addon_smoke.py in an isolated profile.
"""
import base64
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import firefox_addon_smoke as smoke


BUILD_ID = "20261123184640"


class UnitMarionetteDouble:
    """Scripted transport for receipt/verdict boundaries, not browser evidence."""

    def __init__(self, root, observed_build, uninstall_error):
        self.root = root
        self.observed_build = observed_build
        self.uninstall_error = uninstall_error
        self.greeting = {"unitTestDouble": True}
        self.commands = []
        self.socket = Mock()
        self.handles_requested = 0
        self.clicks = []
        self.report = {"complete": True, "webgl": {"status": "pass"}, "webgpu": {}}
        self.script_results = iter([
            True,
            [{"tag": "unit-toolbar-item", "id": "unit-action", "action": True}],
            "BUTTON",
            True,
            {"url": "moz-extension://unit-test-double/diagnostics.html", "version": "v0.1.0",
             "progress": "Ready", "saveDisabled": True, "report": "No checks have run."},
            {"running": False, "saveDisabled": False, "progress": "Done",
             "report": json.dumps(self.report)},
        ])

    def command(self, name, params=None):
        self.commands.append({"command": name, "params": params})
        if name == "WebDriver:NewSession":
            capabilities = {"moz:profile": str(self.root / "profile")}
            if self.observed_build is not None:
                capabilities["moz:buildID"] = self.observed_build
            return {"capabilities": capabilities}
        if name == "Addon:Install":
            return {"value": smoke.ADDON_ID}
        if name == "WebDriver:GetWindowHandles":
            self.handles_requested += 1
            return ["unit-blank"] if self.handles_requested == 1 else ["unit-blank", "unit-diagnostics"]
        if name == "WebDriver:TakeScreenshot":
            return {"value": base64.b64encode(b"unit-test-double-not-a-real-image").decode()}
        if name == "Addon:Uninstall" and self.uninstall_error:
            raise RuntimeError("unit-test uninstall failure")
        if name not in {"WebDriver:SetTimeouts", "Marionette:SetContext", "WebDriver:SwitchToWindow",
                        "Addon:Uninstall", "Marionette:Quit"}:
            raise AssertionError(f"Unexpected unit transport command: {name}")
        return {}

    def script(self, script, args=None):
        return next(self.script_results)

    def click(self, selector):
        self.clicks.append(selector)
        if selector == "#download":
            (self.root / "downloads/are-firefox-graphics-report.json").write_text(json.dumps(self.report))


class FirefoxAddonSmokeUnitTests(unittest.TestCase):
    def run_harness_unit(self, observed_build=BUILD_ID, uninstall_error=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            run = root / "unit-run"
            package, binary, install = root / "unit.xpi", root / "unit-firefox", root / "install.json"
            package.write_bytes(b"unit-package-not-an-extension")
            binary.write_bytes(b"unit-browser-not-executable")
            install.write_text(json.dumps({"expectedBuildId": BUILD_ID,
                                          "files": {"firefox": {"path": str(binary), "sha256": smoke.sha(binary)}}}))
            client = UnitMarionetteDouble(run, observed_build, uninstall_error)
            process = Mock(returncode=0)
            process.poll.return_value = None
            process.wait.return_value = 0
            output = io.StringIO()
            with ExitStack() as stack:
                stack.enter_context(patch.object(sys, "argv", ["firefox_addon_smoke.py", "--package", str(package),
                                                               "--install-receipt", str(install), "--output-dir", str(run)]))
                stack.enter_context(patch.object(smoke.os, "geteuid", return_value=997, create=True))
                stack.enter_context(patch.object(smoke.os, "umask"))
                reservation = stack.enter_context(patch.object(smoke.socket, "socket"))
                reservation.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 12345)
                stack.enter_context(patch.object(smoke.subprocess, "Popen", return_value=process))
                stack.enter_context(patch.object(smoke, "Marionette", return_value=client))
                # Isolate control flow; this acceptance is a unit double, never a pixel/runtime claim.
                stack.enter_context(patch.object(smoke, "verify_pixels", return_value={"acceptedPass": True,
                                                                                     "reportedStatus": "pass"}))
                stack.enter_context(redirect_stdout(output))
                exit_code = smoke.main()
            receipt = json.loads((run / "runtime-receipt.json").read_text())
            return exit_code, receipt, json.loads(output.getvalue()), client

    def test_uninstall_failure_overrides_prior_success_and_returns_failure(self):
        exit_code, receipt, printed, client = self.run_harness_unit(uninstall_error=True)
        self.assertIn("#run", client.clicks)
        self.assertTrue(receipt["cases"]["webgl"]["acceptedPass"])
        self.assertEqual(receipt["error"]["message"], "unit-test uninstall failure")
        self.assertEqual(exit_code, 1)
        self.assertFalse(receipt["passed"])
        self.assertFalse(printed["passed"])
        self.assertNotIn("temporaryAddonRemoved", receipt)

    def test_mismatched_running_build_is_recorded_and_stops_before_install(self):
        exit_code, receipt, printed, client = self.run_harness_unit(observed_build="20261124093648")
        self.assertEqual(exit_code, 1)
        self.assertFalse(receipt["passed"])
        self.assertFalse(printed["passed"])
        self.assertEqual(receipt["browserBuildId"], "20261124093648")
        self.assertIn("build ID", receipt["error"]["message"])
        self.assertNotIn("Addon:Install", [entry["command"] for entry in client.commands])
        self.assertEqual(client.clicks, [])

    def test_missing_running_build_fails_without_claiming_expected_value(self):
        exit_code, receipt, printed, client = self.run_harness_unit(observed_build=None)
        self.assertEqual(exit_code, 1)
        self.assertFalse(receipt["passed"])
        self.assertFalse(printed["passed"])
        self.assertIsNone(receipt["browserBuildId"])
        self.assertIn("build ID", receipt["error"]["message"])
        self.assertNotIn("Addon:Install", [entry["command"] for entry in client.commands])
        self.assertEqual(client.clicks, [])

    def test_matching_running_build_preserves_success_and_cleanup(self):
        exit_code, receipt, printed, client = self.run_harness_unit()
        self.assertEqual(exit_code, 0)
        self.assertTrue(receipt["passed"])
        self.assertTrue(printed["passed"])
        self.assertEqual(receipt["browserBuildId"], BUILD_ID)
        self.assertTrue(receipt["temporaryAddonRemoved"])
        self.assertEqual(client.clicks, ["#run", "#download"])
        self.assertNotIn("error", receipt)


if __name__ == "__main__":
    unittest.main()
