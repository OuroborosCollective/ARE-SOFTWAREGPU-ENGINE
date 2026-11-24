#!/usr/bin/env python3
"""Build a native Windows x64 setup EXE or Linux x86_64 offline installer.

The embedded Python CPU renderer is an application, not an OS GPU driver.
Build on the target OS with the versioned distribution installed beforehand.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version as distribution_version
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "packaging" / "desktop"


def validate_version(value: str) -> str:
    if re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", value) is None:
        raise ValueError("DESKTOP_VERSION_MUST_BE_CANONICAL_STABLE_SEMVER")
    if any(int(part) > 65535 for part in value.split(".")):
        raise ValueError("DESKTOP_VERSION_EXCEEDS_WINDOWS_VERSION_FIELD")
    return value


def platform_name() -> str:
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ValueError("DESKTOP_BUILD_REQUIRES_X86_64")
    if sys.platform == "win32":
        return "windows-x64"
    if sys.platform.startswith("linux"):
        return "linux-x86_64"
    raise ValueError("UNSUPPORTED_DESKTOP_BUILD_PLATFORM")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _tar_metadata(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    return info


def build_linux_installer(bundle: Path, output: Path, version: str) -> None:
    validate_version(version)
    if output.exists():
        raise ValueError("DESKTOP_OUTPUT_ALREADY_EXISTS")
    with tempfile.TemporaryDirectory(prefix="are-linux-package-") as tmp:
        work = Path(tmp)
        content = work / "content"
        content.mkdir()
        shutil.copytree(bundle, content / "app", symlinks=True)
        (content / "bin").mkdir()
        # Relative symlink keeps a relocated per-user installation functional.
        (content / "bin" / "are-softwaregpu").symlink_to("../app/are-softwaregpu")
        shutil.copyfile(TEMPLATES / "linux-uninstall.sh", content / "uninstall.sh")
        (content / "uninstall.sh").chmod(0o755)
        files, directories = [], []
        for path in sorted(content.rglob("*")):
            name = path.relative_to(content).as_posix()
            if any(c in name for c in "\r\n\\"):
                raise ValueError("UNSAFE_PACKAGE_MEMBER_NAME")
            if path.is_symlink():
                if not path.resolve().is_relative_to(content.resolve()):
                    raise ValueError("PACKAGE_SYMLINK_ESCAPES_INSTALLATION")
                files.append(name)
            elif path.is_file():
                files.append(name)
            elif path.is_dir():
                directories.append(name)
            else:
                raise ValueError("UNSUPPORTED_PACKAGE_MEMBER")
        files.remove("uninstall.sh")
        (content / ".are-uninstall-files").write_text("\n".join(files) + "\n", encoding="utf-8")
        directories.sort(key=lambda name: (name.count("/"), name), reverse=True)
        (content / ".are-uninstall-dirs").write_text("\n".join(directories) + "\n", encoding="utf-8")
        payload = work / "payload.tar.gz"
        with tarfile.open(payload, "w:gz", dereference=False) as archive:
            for path in sorted(content.rglob("*")):
                archive.add(path, arcname=path.relative_to(content).as_posix(), recursive=False, filter=_tar_metadata)
        header = (TEMPLATES / "linux-install.sh.in").read_text(encoding="utf-8")
        header = header.replace("@VERSION@", version).replace("@PAYLOAD_SHA256@", digest(payload))
        header = header.replace("@PAYLOAD_LINE@", str(header.count("\n") + 1))
        with output.open("xb") as target, payload.open("rb") as source:
            target.write(header.encode("utf-8"))
            shutil.copyfileobj(source, target)
        output.chmod(0o755)


def source_clean(source_sha: str) -> bool:
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise ValueError("FULL_SOURCE_COMMIT_SHA_REQUIRED")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if actual != source_sha:
        raise ValueError("DESKTOP_SOURCE_COMMIT_MISMATCH")
    status = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, text=True)
    return not status.strip()


def build(version: str, source_sha: str, output_dir: Path, *, iscc: str | None = None,
          allow_dirty: bool = False) -> Path:
    validate_version(version)
    platform_id = platform_name()
    clean = source_clean(source_sha)
    if not clean and not allow_dirty:
        raise ValueError("DESKTOP_RELEASE_REQUIRES_CLEAN_SOURCE")
    if distribution_version("ouroboroscollective-softwaregpu") != version:
        raise ValueError("INSTALLED_DISTRIBUTION_VERSION_MISMATCH")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="are-desktop-build-") as tmp:
        work = Path(tmp)
        metadata = {
            "schema": "are.desktop-build.v1", "version": version,
            "source_sha": source_sha, "source_clean": clean, "platform": platform_id,
            "runtime": "embedded Python CPU renderer", "system_gpu_driver_installed": False,
        }
        metadata_file = work / "release.json"
        metadata_file.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        cmd = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "--onedir", "--noupx",
               "--name", "are-softwaregpu", "--distpath", str(work / "dist"),
               "--workpath", str(work / "build"), "--specpath", str(work), "--paths", str(ROOT),
               "--copy-metadata", "ouroboroscollective-softwaregpu", "--copy-metadata", "numpy",
               "--copy-metadata", "Pillow", "--copy-metadata", "pyinstaller",
               "--add-data", str(metadata_file) + os.pathsep + ".", str(ROOT / "tools" / "desktop_entry.py")]
        subprocess.run(cmd, cwd=ROOT, check=True, timeout=1200)
        bundle = work / "dist" / "are-softwaregpu"
        exe = bundle / ("are-softwaregpu.exe" if sys.platform == "win32" else "are-softwaregpu")
        if not exe.is_file():
            raise ValueError("FROZEN_ENGINE_EXECUTABLE_MISSING")
        for name in ("LICENSE.md", "NOTICE"):
            shutil.copyfile(ROOT / name, bundle / name)
        python_license = next((p for p in (
            Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
        ) if p.is_file()), None)
        if python_license is None:
            raise ValueError("EMBEDDED_PYTHON_LICENSE_MISSING")
        shutil.copyfile(python_license, bundle / "PYTHON-LICENSE.txt")
        if platform_id == "windows-x64":
            # cmd /k keeps the console open after help; no unrequested benchmark.
            (bundle / "ARE SoftwareGPU Console.cmd").write_bytes(
                b'@echo off\r\nsetlocal\r\nset "PATH=%~dp0;%PATH%"\r\n"%~dp0are-softwaregpu.exe" --help\r\ncmd /k\r\nendlocal\r\n')
            compiler = iscc or shutil.which("ISCC.exe") or str(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe")
            if not Path(compiler).is_file():
                raise ValueError("INNO_SETUP_COMPILER_MISSING")
            subprocess.run([compiler, "/Qp", "/DVersion=" + version, "/DSourceDir=" + str(bundle),
                            "/DOutputDir=" + str(output_dir), str(TEMPLATES / "windows.iss")], check=True, timeout=600)
            artifact = output_dir / f"ARE-SoftwareGPU-{version}-windows-x64-setup.exe"
        else:
            artifact = output_dir / f"ARE-SoftwareGPU-{version}-linux-x86_64.run"
            build_linux_installer(bundle, artifact, version)
        receipt = {"schema": "are.desktop-release.v1", "version": version, "source_sha": source_sha,
                   "source_clean": clean, "platform": platform_id,
                   "artifact": {"name": artifact.name, "sha256": digest(artifact), "bytes": artifact.stat().st_size},
                   "embedded_executable_sha256": digest(exe), "embedded_python": platform.python_version(),
                   "pyinstaller": distribution_version("pyinstaller"), "system_gpu_driver_installed": False,
                   "signed": False}
        receipt_path = output_dir / f"desktop-{platform_id}.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(receipt, sort_keys=True))
        return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--iscc", help="Absolute Inno Setup compiler path on Windows")
    parser.add_argument("--allow-dirty", action="store_true", help="Local development only; receipt is ineligible for publication")
    args = parser.parse_args()
    build(args.version, args.source_sha, args.output_dir, iscc=args.iscc, allow_dirty=args.allow_dirty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
