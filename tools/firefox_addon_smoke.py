"""Exercise an unsigned add-on in a real, isolated Firefox via Marionette.

Only Python's standard library is used. The graphics implementation is never
replaced: this client presses UI buttons and verifies the downloaded raw bytes.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time


ADDON_ID = "are-softwaregpu-diagnostics@arelogic.space"


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Marionette:
    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=20)
        self.sequence = 0
        self.greeting = self.receive()
        self.commands = []

    def receive(self):
        prefix = bytearray()
        while True:
            byte = self.socket.recv(1)
            if not byte:
                raise EOFError("Marionette closed the socket")
            if byte == b":":
                break
            prefix.extend(byte)
            if len(prefix) > 9 or not byte.isdigit():
                raise ValueError("Invalid Marionette frame")
        length = int(prefix)
        if not 0 < length <= 16 * 1024 * 1024:
            raise ValueError("Marionette frame size out of range")
        data = bytearray()
        while len(data) < length:
            block = self.socket.recv(length - len(data))
            if not block:
                raise EOFError("Incomplete Marionette frame")
            data.extend(block)
        return json.loads(data)

    def command(self, name, params=None):
        self.sequence += 1
        data = json.dumps([0, self.sequence, name, params or {}]).encode()
        self.socket.sendall(str(len(data)).encode() + b":" + data)
        reply = self.receive()
        self.commands.append({"sequence": self.sequence, "command": name,
                              "error": reply[2] if isinstance(reply, list) and len(reply) == 4 else "invalid response"})
        if not isinstance(reply, list) or len(reply) != 4 or reply[:2] != [1, self.sequence]:
            raise ValueError("Marionette response identity mismatch")
        if reply[2]:
            raise RuntimeError(json.dumps(reply[2]))
        return reply[3]

    def script(self, script, args=None):
        return self.command("WebDriver:ExecuteScript", {
            "script": script, "args": args or [], "newSandbox": True,
            "sandbox": "default", "line": 1, "filename": "firefox_addon_smoke.py",
        })["value"]

    def click(self, selector):
        value = self.command("WebDriver:FindElement", {"using": "css selector", "value": selector})["value"]
        self.command("WebDriver:ElementClick", {"id": value["element-6066-11e4-a52e-4f735466cecf"]})


def verify_pixels(record):
    """Independent row-width oracle; consumes only the actual exported bytes."""
    evidence = {"reportedStatus": record.get("status"), "acceptedPass": False}
    payload = record.get("readback")
    if not payload:
        evidence["reason"] = "No pixel payload; no rendering claim."
        return evidence
    raw = base64.b64decode(payload["payloadBase64"], validate=True)
    if len(raw) != 16384 or payload.get("origin") not in ("bottom-left", "top-left"):
        raise ValueError("Unexpected readback layout")
    mismatches = 0
    for row in range(64):
        y = row + 0.5 if payload["origin"] == "bottom-left" else 63.5 - row
        half_width = (56 - y) / 2
        for x in range(64):
            inside = 8 < y < 56 and abs(x + 0.5 - 32) < half_width
            expected = b"\xff\0\0\xff" if inside else b"\0\0\xff\xff"
            index = (row * 64 + x) * 4
            mismatches += raw[index:index + 4] != expected
    actual_hash = hashlib.sha256(raw).hexdigest()
    metadata = {"width": 64, "height": 64, "rowStrideBytes": 256,
                "format": "RGBA8", "byteLength": 16384, "payloadEncoding": "base64"}
    valid = all(payload.get(key) == value for key, value in metadata.items())
    valid = valid and payload.get("sha256") == actual_hash and mismatches == 0
    valid = valid and payload.get("mismatchedPixels") == 0 and payload.get("matches") is True
    no_errors = not any(record.get(key) for key in ("errors", "deviceLost", "contextLoss", "cleanupErrors"))
    no_errors = no_errors and not any(item.get("type") == "error" for item in record.get("shaderMessages", []))
    evidence.update({"bytes": len(raw), "sha256": actual_hash, "mismatchedPixels": mismatches,
                     "readbackVerified": valid,
                     "acceptedPass": valid and no_errors and record.get("status") == "pass" and record.get("acceptedPass") is True})
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--install-receipt", type=Path, required=True,
                        help="Pinned Firefox receipt with files[path, sha256] and expectedBuildId")
    parser.add_argument("--output-dir", type=Path, required=True, help="New isolated run directory")
    parser.add_argument("--require-uid", type=int)
    args = parser.parse_args()
    if os.geteuid() == 0 or (args.require_uid is not None and os.geteuid() != args.require_uid):
        raise SystemExit("Run as the designated unprivileged test user")
    os.umask(0o077)
    root = args.output_dir.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    profile, downloads, runtime = root / "profile", root / "downloads", root / "xdg-runtime"
    for directory in (profile, downloads, runtime):
        directory.mkdir(mode=0o700)
    package = args.package.resolve(strict=True)
    install = json.loads(args.install_receipt.read_text())
    files = install["files"]
    hashes_before = {name: sha(spec["path"]) for name, spec in files.items()}
    if any(hashes_before[name] != spec["sha256"] for name, spec in files.items()):
        raise SystemExit("Pinned browser file changed")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    prefs = {
        "marionette.port": port, "browser.shell.checkDefaultBrowser": False,
        "browser.aboutwelcome.enabled": False, "browser.startup.homepage_override.mstone": "ignore",
        "browser.download.folderList": 2, "browser.download.dir": str(downloads),
        "browser.download.useDownloadDir": True, "browser.download.always_ask_before_handling_new_types": False,
        "browser.helperApps.neverAsk.saveToDisk": "application/json",
    }
    (profile / "user.js").write_text("".join(f"user_pref({json.dumps(key)}, {json.dumps(value)});\n" for key, value in prefs.items()))
    env = os.environ.copy()
    remove = {"PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "LD_PRELOAD", "DISPLAY", "WAYLAND_DISPLAY",
              "XAUTHORITY", "MOZ_HEADLESS", "MOZ_ENABLE_WAYLAND", "MOZ_WEBRENDER", "MOZ_X11_EGL",
              "MOZ_FORCE_DISABLE_E10S", "LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER", "MESA_LOADER_DRIVER_OVERRIDE",
              "LIBGL_DRIVERS_PATH", "__GLX_VENDOR_LIBRARY_NAME"}
    for key in list(env):
        if key in remove or key.startswith(("VK_", "ARE_", "MOZ_DISABLE_")):
            env.pop(key, None)
    selected_environment = {"XDG_RUNTIME_DIR": str(runtime), "LP_NUM_THREADS": "2", "OMP_NUM_THREADS": "1",
                            "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS": "1"}
    env.update(selected_environment)
    command = ["nice", "-n", "10", "xvfb-run", "-a", "-n", "191", "-s",
               "-screen 0 1100x1000x24 -nolisten tcp", files["firefox"]["path"],
               "-no-remote", "-profile", str(profile), "--marionette", "about:blank"]
    receipt = {"schema": "are.firefox-addon-smoke.v1", "uid": os.geteuid(), "packageSha256": sha(package),
               "harnessSha256": sha(__file__), "browserBuildId": None,
               "expectedBrowserBuildId": install["expectedBuildId"],
               "browserFilesBefore": hashes_before, "profilePreferences": prefs, "processEnvironment": selected_environment,
               "command": command, "scope": "Temporary local add-on UI and actual shader/readback; no ARE driver attribution or AMO approval.",
               "passed": False}
    client = proc = None
    try:
        with (root / "firefox.stdout.log").open("wb") as out, (root / "firefox.stderr.log").open("wb") as err:
            proc = subprocess.Popen(command, stdout=out, stderr=err, env=env, cwd=root, start_new_session=True)
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError("Firefox launcher exited before Marionette connected")
                try:
                    client = Marionette(port)
                    break
                except ConnectionRefusedError:
                    time.sleep(0.2)
            if not client:
                raise TimeoutError("Marionette did not start")
            receipt["greeting"] = client.greeting
            receipt["session"] = client.command("WebDriver:NewSession")
            actual_profile = receipt["session"].get("capabilities", {}).get("moz:profile")
            if not actual_profile or Path(actual_profile).resolve() != profile:
                # Never install into or automate another browser if a port was taken.
                client.socket.close()
                client = None
                raise ValueError("Marionette session is not the newly created test profile")
            receipt["profileBound"] = True
            receipt["browserBuildId"] = receipt["session"].get("capabilities", {}).get("moz:buildID")
            if (not isinstance(receipt["browserBuildId"], str) or not receipt["browserBuildId"]
                    or receipt["browserBuildId"] != install["expectedBuildId"]):
                raise ValueError("Running Firefox build ID is missing or differs from the pinned expected build ID")
            client.command("WebDriver:SetTimeouts", {"script": 10000, "pageLoad": 20000, "implicit": 0})
            receipt["installedId"] = client.command("Addon:Install", {"path": str(package), "temporary": True})["value"]
            if receipt["installedId"] != ADDON_ID:
                raise ValueError("Installed add-on identity differs")
            before = client.command("WebDriver:GetWindowHandles")
            client.command("Marionette:SetContext", {"value": "chrome"})
            receipt["toolbarOpen"] = client.script("document.getElementById('unified-extensions-button').click(); return true;")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                candidates = client.script("return [...document.querySelectorAll('[data-extensionid]')].filter(e => e.getAttribute('data-extensionid') === arguments[0]).map(e => ({tag:e.tagName,id:e.id,action:!!e.querySelector('.unified-extensions-item-action-button')}));", [ADDON_ID])
                if candidates:
                    break
                time.sleep(0.1)
            receipt["toolbarCandidates"] = candidates
            receipt["toolbarClicked"] = client.script("const e=[...document.querySelectorAll('[data-extensionid]')].find(e=>e.getAttribute('data-extensionid')===arguments[0]); if (!e) throw new Error('Add-on action not found'); const b=e.querySelector('.unified-extensions-item-action-button')||e; b.click(); return b.tagName;", [ADDON_ID])
            client.command("Marionette:SetContext", {"value": "content"})
            deadline = time.monotonic() + 10
            handles = before
            while time.monotonic() < deadline:
                handles = client.command("WebDriver:GetWindowHandles")
                if len(handles) > len(before):
                    break
                time.sleep(0.2)
            new_tabs = [handle for handle in handles if handle not in before]
            if len(new_tabs) != 1:
                raise ValueError("Toolbar did not open exactly one diagnostics tab")
            client.command("WebDriver:SwitchToWindow", {"handle": new_tabs[0], "focus": True})
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                ready = client.script("return !!document.getElementById('run') && document.getElementById('version')?.textContent === 'v0.1.0';")
                if ready:
                    break
                time.sleep(0.2)
            receipt["initialUi"] = client.script("return {url:location.href,version:document.getElementById('version').textContent,progress:document.getElementById('progress').textContent,saveDisabled:document.getElementById('download').disabled,report:document.getElementById('report').textContent};")
            if not receipt["initialUi"]["url"].startswith("moz-extension://") or receipt["initialUi"]["saveDisabled"] is not True or receipt["initialUi"]["report"] != "No checks have run.":
                raise ValueError("Unexpected initial extension UI")
            client.click("#run")
            deadline = time.monotonic() + 85
            while time.monotonic() < deadline:
                state = client.script("return {running:document.getElementById('run').disabled,saveDisabled:document.getElementById('download').disabled,progress:document.getElementById('progress').textContent,report:document.getElementById('report').textContent};")
                if not state["running"]:
                    break
                time.sleep(0.3)
            receipt["finalUi"] = {key: value for key, value in state.items() if key != "report"}
            if state["running"] or state["saveDisabled"]:
                raise RuntimeError("Diagnostics did not finish with an exportable result")
            report = json.loads(state["report"])
            (root / "dom-report.json").write_text(json.dumps(report, indent=2) + "\n")
            client.click("#download")
            downloaded = downloads / "are-firefox-graphics-report.json"
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not downloaded.is_file():
                time.sleep(0.2)
            receipt["downloadMatchesDom"] = json.loads(downloaded.read_text()) == report
            screenshot = client.command("WebDriver:TakeScreenshot", {"id": None, "full": True, "hash": False, "scroll": True, "readback": False})["value"]
            (root / "diagnostics.png").write_bytes(base64.b64decode(screenshot, validate=True))
            receipt["screenshotSha256"] = sha(root / "diagnostics.png")
            receipt["reportSha256"] = sha(downloaded)
            receipt["cases"] = {"webgl": verify_pixels(report["webgl"]),
                                **{name: verify_pixels(record) for name, record in report["webgpu"].items()}}
            for name, record in [("webgl", report["webgl"]), *report["webgpu"].items()]:
                if record.get("readback"):
                    (root / (name + ".rgba")).write_bytes(base64.b64decode(record["readback"]["payloadBase64"], validate=True))
            receipt["passed"] = (report.get("complete") is True and not report.get("fatalError")
                                 and receipt["downloadMatchesDom"] and receipt["cases"]["webgl"]["acceptedPass"]
                                 and all(case["acceptedPass"] or case["reportedStatus"] == "unavailable" for case in receipt["cases"].values()))
            client.command("Addon:Uninstall", {"id": ADDON_ID})
            receipt["temporaryAddonRemoved"] = True
    except Exception as error:
        receipt["passed"] = False
        receipt["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if client:
            receipt["commands"] = client.commands
            try:
                client.command("Marionette:Quit", {"flags": ["eForceQuit"]})
            except (OSError, RuntimeError, EOFError):
                pass
            client.socket.close()
        if proc:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
            receipt["launcherExitCode"] = proc.returncode
        receipt["browserFilesAfter"] = {name: sha(spec["path"]) for name, spec in files.items()}
        receipt["browserUnchanged"] = receipt["browserFilesAfter"] == hashes_before
        receipt["packageUnchanged"] = sha(package) == receipt["packageSha256"]
        receipt["passed"] = receipt["passed"] and receipt["browserUnchanged"] and receipt["packageUnchanged"]
        (root / "runtime-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"passed": receipt["passed"], "directory": str(root), "cases": receipt.get("cases"),
                          "error": receipt.get("error"), "receiptSha256": sha(root / "runtime-receipt.json")}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
