#!/usr/bin/env python3
"""Actually install, launch, read back and uninstall an APK on an isolated emulator."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

if __package__:
    from .android_release import verify_apk, write_json
    from .platform_release import digest
    from .release_gate import ReleaseGateError
else:
    from android_release import verify_apk, write_json
    from platform_release import digest
    from release_gate import ReleaseGateError

PACKAGE = "de.arelorian.softwaregpu"


def assert_serial_unused(listing, serial):
    if any(line.split()[0] == serial for line in listing.splitlines() if line.split()):
        raise ReleaseGateError("The smoke-test emulator serial is already in use; no device was changed")


def run_smoke(apk, tag, sha, output_dir, avd, scope):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    metadata = verify_apk(apk, tag, sha, scope)
    sdk = Path(os.environ.get("ANDROID_HOME") or os.environ["ANDROID_SDK_ROOT"])
    serial = "emulator-5554"
    adb = sdk / "platform-tools/adb"
    devices = subprocess.run([str(adb), "devices"], capture_output=True, text=True,
                             encoding="utf-8", check=True, timeout=20)
    assert_serial_unused(devices.stdout, serial)

    def command(*args, timeout=40, check=True):
        process = subprocess.run([str(adb), "-s", serial, *args], capture_output=True,
                                 text=True, encoding="utf-8", timeout=timeout)
        if check and process.returncode:
            raise ReleaseGateError(f"adb {args[0]} failed: {process.stderr[-2000:]}")
        return process.stdout.strip()

    # This helper exclusively addresses a fresh CI emulator, never a physical device.
    log = (output / "emulator.log").open("wb")
    emulator = subprocess.Popen([str(sdk / "emulator/emulator"), "-avd", avd, "-port", "5554",
                                 "-no-window", "-no-audio", "-no-boot-anim", "-no-snapshot", "-wipe-data",
                                 "-gpu", "swiftshader_indirect", "-accel", "on"], stdout=log, stderr=subprocess.STDOUT)
    installed = False
    try:
        for attempt in range(90):
            if emulator.poll() is not None:
                raise ReleaseGateError("Android emulator stopped before boot completed; inspect emulator.log")
            if command("shell", "getprop", "sys.boot_completed", check=False) == "1":
                break
            if attempt % 6 == 0:
                print(f"Waiting for real Android emulator boot ({attempt * 5}s)", flush=True)
            time.sleep(5)
        else:
            raise ReleaseGateError("Android emulator boot timed out")
        if emulator.poll() is not None:
            raise ReleaseGateError("Our emulator process stopped before installation")
        if command("shell", "getprop", "ro.kernel.qemu") != "1":
            raise ReleaseGateError("Install smoke requires an emulator")
        api = command("shell", "getprop", "ro.build.version.sdk")
        if api != "35":
            raise ReleaseGateError("Install smoke requires Android API 35")
        command("shell", "input", "keyevent", "82")
        result = command("install", "--no-streaming", str(Path(apk).resolve()), timeout=60)
        if "Success" not in result:
            raise ReleaseGateError("APK installation was not acknowledged")
        installed = True
        launched = command("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity")
        (output / "activity-start.txt").write_text(launched + "\n", encoding="utf-8")
        if not re.search(r"^Status: ok$", launched, re.M):
            raise ReleaseGateError("Android activity did not report a successful launch")
        required_text = {"Dein erster Grafiktest", "Testlabor öffnen", "ARE  /  CPU-TESTLABOR"}
        observed = set()
        for attempt in range(8):
            command("shell", "uiautomator", "dump", "/sdcard/are-window.xml")
            xml = command("shell", "cat", "/sdcard/are-window.xml")
            (output / "welcome-ui.xml").write_text(xml, encoding="utf-8")
            tree = ET.fromstring(xml)
            observed.update(node.get("text", "") for node in tree.iter("node") if node.get("package") == PACKAGE)
            if required_text <= observed:
                break
            if attempt >= 2:
                command("shell", "input", "swipe", "500", "1600", "500", "500", "300")
            time.sleep(2)
        if not required_text <= observed:
            raise ReleaseGateError("Actual Android welcome UI did not expose the expected controls")
        pid = command("shell", "pidof", PACKAGE)
        if not re.fullmatch(r"[1-9][0-9]*(?: [1-9][0-9]*)*", pid):
            raise ReleaseGateError("Android companion process is not alive")
        remote = command("shell", "pm", "path", PACKAGE)
        if not re.fullmatch(r"package:/data/app/[^\r\n]+/base\.apk", remote):
            raise ReleaseGateError("Installed package did not return a unique APK")
        with tempfile.TemporaryDirectory(prefix="are-installed-apk-") as directory:
            readback = Path(directory) / "installed.apk"
            command("pull", remote.removeprefix("package:"), str(readback), timeout=60)
            if digest(readback) != metadata["artifact"]["sha256"]:
                raise ReleaseGateError("Installed Android APK bytes differ from signed release")
        screenshot = subprocess.run([str(adb), "-s", serial, "exec-out", "screencap", "-p"],
                                    capture_output=True, check=True, timeout=20)
        (output / "welcome.png").write_bytes(screenshot.stdout)
        if command("uninstall", PACKAGE) != "Success":
            raise ReleaseGateError("Android uninstall was not acknowledged")
        installed = False
        if command("shell", "pm", "path", PACKAGE, check=False).startswith("package:"):
            raise ReleaseGateError("Package remained installed after uninstall")
        receipt = {"schema": "are.android-emulator-smoke.v1", "passed": True,
                   "source_sha": sha, "version": metadata["version"], "apk_sha256": metadata["artifact"]["sha256"],
                   "signing_scope": scope, "device_kind": "emulator", "android_api": int(api),
                   "checks": {key: True for key in ("install", "launch", "process_alive", "welcome_ui", "installed_apk_bytes", "uninstall")},
                   "rendering_scope": "HTTPS companion welcome only; no native renderer or remote server test"}
        write_json(output / "android-emulator-smoke.json", receipt)
        return receipt
    finally:
        try:
            try:
                (output / "logcat.txt").write_text(command("logcat", "-d", check=False), encoding="utf-8")
                if installed:
                    command("uninstall", PACKAGE, check=False)
                command("emu", "kill", check=False)
            except (OSError, subprocess.TimeoutExpired) as error:
                # Preserve the original failure; diagnostics are never a success receipt.
                (output / "cleanup-error.txt").write_text(type(error).__name__ + "\n", encoding="utf-8")
        finally:
            emulator.terminate()
            try:
                emulator.wait(timeout=15)
            except subprocess.TimeoutExpired:
                emulator.kill()
                emulator.wait(timeout=5)
            log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--avd", default="are_release")
    parser.add_argument("--scope", choices=("release", "ci-test"), required=True)
    args = parser.parse_args()
    print(json.dumps(run_smoke(args.apk, args.tag, args.sha, args.output_dir, args.avd, args.scope), sort_keys=True))


if __name__ == "__main__":
    main()
