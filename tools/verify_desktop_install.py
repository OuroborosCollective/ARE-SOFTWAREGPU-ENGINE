#!/usr/bin/env python3
"""Install the real desktop package, render outside checkout, and uninstall.

Run on disposable native Windows/Linux CI workers. No browser, GPU adapter,
game runtime, or hardware performance claim is derived from this smoke test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time

from package_desktop import digest, platform_name, validate_version


ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, check=False, timeout=240,
                            text=True, encoding="utf-8", errors="replace", capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    result.check_returncode()
    return result.stdout


def bmp_summary(data: bytes) -> dict:
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError("RENDER_IS_NOT_BMP")
    size, offset = struct.unpack_from("<I4xI", data, 2)
    width, height, planes, bpp, compression = struct.unpack_from("<iiHHI", data, 18)
    if size != len(data) or (width, abs(height), planes, bpp, compression) != (320, 240, 1, 24, 0):
        raise ValueError("RENDER_BMP_LAYOUT_MISMATCH")
    stride = (width * 3 + 3) & ~3
    if offset < 54 or offset + stride * abs(height) != len(data):
        raise ValueError("RENDER_BMP_LENGTH_MISMATCH")
    pixels = data[offset:]
    colors = [pixels[i:i + 3] for row in range(abs(height)) for i in range(row * stride, row * stride + width * 3, 3)]
    # The existing Blender demo has constant normals and a flat diffuse color;
    # two colors are correct. Require both clear background and real coverage.
    background = colors.count(bytes([42, 34, 30]))
    foreground = width * abs(height) - background
    if background == 0 or foreground == 0:
        raise ValueError("RENDER_HAS_NO_SHADED_GEOMETRY")
    return {"width": width, "height": abs(height), "bytes": len(data), "unique_rgb_colors": len(set(colors)),
            "background_pixels": background, "foreground_pixels": foreground,
            "sha256": hashlib.sha256(data).hexdigest()}


def verify(directory: Path, version: str, source_sha: str, receipt_path: Path,
           *, allow_dirty: bool = False) -> dict:
    validate_version(version)
    if receipt_path.exists():
        raise ValueError("DESKTOP_SMOKE_RECEIPT_ALREADY_EXISTS")
    platform_id = platform_name()
    build = json.loads((directory / f"desktop-{platform_id}.json").read_text(encoding="utf-8"))
    if (build.get("schema"), build.get("version"), build.get("source_sha"), build.get("platform")) != (
        "are.desktop-release.v1", version, source_sha, platform_id
    ):
        raise ValueError("DESKTOP_BUILD_RECEIPT_IDENTITY_MISMATCH")
    if build.get("source_clean") is not True and not allow_dirty:
        raise ValueError("DESKTOP_SMOKE_REQUIRES_CLEAN_RELEASE_SOURCE")
    suffix = "windows-x64-setup.exe" if sys.platform == "win32" else "linux-x86_64.run"
    name = f"ARE-SoftwareGPU-{version}-{suffix}"
    artifact = directory / name
    if build.get("artifact") != {"name": name, "sha256": digest(artifact), "bytes": artifact.stat().st_size}:
        raise ValueError("DESKTOP_INSTALLER_DIGEST_MISMATCH")
    checks = {}
    with tempfile.TemporaryDirectory(prefix="are real desktop install ") as tmp:
        work = Path(tmp)
        prefix = work / "installed application"
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["ARE_LEARNING_DB"] = "off"
        if sys.platform == "win32":
            run([str(artifact.resolve()), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                 "/CURRENTUSER", "/DIR=" + str(prefix)], work, env)
            exe = prefix / "are-softwaregpu.exe"
            uninstall = [str(prefix / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
        else:
            run(["sh", str(artifact.resolve()), "--prefix", str(prefix)], work, env)
            exe = prefix / "bin" / "are-softwaregpu"
            uninstall = [str(prefix / "uninstall.sh")]
        if not exe.is_file() or digest(exe) != build["embedded_executable_sha256"]:
            raise ValueError("INSTALLED_EXECUTABLE_DIGEST_MISMATCH")
        checks["install"] = True
        # Both no-argument and explicit help must avoid the costly legacy --all.
        if "--blender" not in run([str(exe)], work, env) or "--server" not in run([str(exe), "--help"], work, env):
            raise ValueError("INSTALLED_CLI_HELP_MISSING")
        checks["help"] = True
        if run([str(exe), "--version"], work, env).strip() != version:
            raise ValueError("INSTALLED_VERSION_MISMATCH")
        checks["version"] = True
        info = json.loads(run([str(exe), "--build-info"], work, env))
        if info.get("source_sha") != source_sha or info.get("version") != version or info.get("platform") != platform_id:
            raise ValueError("INSTALLED_SOURCE_IDENTITY_MISMATCH")
        if info.get("source_clean") is not build["source_clean"]:
            raise ValueError("INSTALLED_SOURCE_CLEAN_FLAG_MISMATCH")
        checks["source"] = True
        if "Device Name:" not in run([str(exe), "--info"], work, env):
            raise ValueError("INSTALLED_DEVICE_INFO_MISSING")
        checks["info"] = True
        outputs = []
        for label, command in (("source", [sys.executable, str(ROOT / "main.py")]), ("installed", [str(exe)])):
            output = work / label
            env["ARE_SOFTWAREGPU_OUTPUT_DIR"] = str(output)
            run(command + ["--blender"], work, env)
            data = (output / "blender_software_gpu_render.bmp").read_bytes()
            bmp_summary(data)
            outputs.append(data)
        if outputs[0] != outputs[1]:
            raise ValueError("INSTALLED_RENDER_DIFFERS_FROM_SOURCE")
        frame = bmp_summary(outputs[1])
        checks["render"] = True
        keep = prefix / "personal.keep"
        keep.write_bytes(b"not owned by the installer\n")
        run(uninstall, work, env)
        if exe.exists() or keep.read_bytes() != b"not owned by the installer\n":
            raise ValueError("UNINSTALL_REMOVED_USER_DATA_OR_LEFT_EXECUTABLE")
        # Inno's uninstaller can finish removing its helper just after exit.
        # Wait boundedly, then require its files to be gone too.
        deadline = time.monotonic() + 10
        while sys.platform == "win32" and list(prefix.glob("unins000.*")) and time.monotonic() < deadline:
            time.sleep(0.1)
        leftovers = [p for p in prefix.rglob("*") if p.is_file() and p != keep]
        if leftovers:
            raise ValueError("UNINSTALL_LEFT_PACKAGE_FILES")
        checks["uninstall"] = True
        checks["user_file_preserved"] = True
    receipt = {"schema": "are.desktop-install-smoke.v1", "source_sha": source_sha,
               "source_clean": build["source_clean"], "version": version, "platform": platform_id,
               "artifact_sha256": build["artifact"]["sha256"], "passed": True, "checks": checks,
               "render": frame, "render_comparison": "full BMP byte equality against actual source execution",
               "runtime": "real installed frozen Python CPU renderer", "synthetic_fixture": False}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true", help="Local development only; not eligible for publication")
    args = parser.parse_args()
    verify(args.directory, args.version, args.source_sha, args.receipt, allow_dirty=args.allow_dirty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
