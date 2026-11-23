"""Actual Vulkan-Loader Lavapipe reference probe (NOT an ARE Vulkan ICD).

The only admissible success requires real unprivileged subprocess execution of
vulkaninfo with VK_DRIVER_FILES restricted to an existing Mesa Lavapipe ICD
manifest. The resulting VkPhysicalDevice belongs to Mesa, never ARE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sysconfig
import tempfile

_CPU = "PHYSICAL_DEVICE_TYPE_CPU"
_API = re.compile(r"1\.\d+\.\d+\Z")
_LIBRARY = re.compile(r"libvulkan_lvp(?:\.so(?:\.[0-9]+)*)?\Z")
_SYSTEM_LIBRARY_DIRS = (Path("/usr/lib"), Path("/lib"))
_DEVICE_TYPE = re.compile(r"^\s*deviceType\s*=\s*([A-Z_0-9]+)\s*$", re.MULTILINE)
_DEVICE_NAME = re.compile(r"^\s*deviceName\s*=\s*(.*?)\s*$", re.MULTILINE)


def _resolve_system_library(declared: str) -> Path:
    library = Path(declared)
    if library.is_absolute():
        candidates = [library]
    else:
        # A bare filename normally uses the dynamic linker's search path.
        # Select an installed file explicitly so that search cannot redirect it.
        multiarch = sysconfig.get_config_var("MULTIARCH")
        directories = [root / multiarch for root in _SYSTEM_LIBRARY_DIRS] if multiarch else []
        candidates = [root / library for root in (*directories, *_SYSTEM_LIBRARY_DIRS)]
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            if not any(resolved.is_relative_to(root) for root in _SYSTEM_LIBRARY_DIRS):
                continue
            if not stat.S_ISREG(resolved.stat().st_mode):
                continue
            # Protect the canonical path against replacement by unprivileged users.
            for component in (resolved, *resolved.parents):
                info = component.stat()
                if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                    break
            else:
                return resolved
        except (OSError, RuntimeError, ValueError):
            continue
    raise ValueError("VULKAN_REFERENCE_UNTRUSTED_LIBRARY")


def _read_reference_manifest(path: Path) -> tuple[dict, dict]:
    path = Path(path).resolve(strict=True)
    if not path.is_file() or not path.name.startswith("lvp_icd") or path.suffix != ".json":
        raise ValueError("VULKAN_REFERENCE_LVP_MANIFEST_REQUIRED")
    raw = path.read_bytes()
    if len(raw) > 65536:
        raise ValueError("VULKAN_REFERENCE_MANIFEST_BUDGET")
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("VULKAN_REFERENCE_MANIFEST_JSON") from exc
    if (type(document) is not dict or
            set(document) != {"file_format_version", "ICD"} or
            document["file_format_version"] not in ("1.0.0", "1.0.1") or
            type(document["ICD"]) is not dict):
        raise ValueError("VULKAN_REFERENCE_MANIFEST_SCHEMA")
    icd = document["ICD"]
    if (not {"library_path", "api_version"}.issubset(icd) or
            not set(icd).issubset({"library_path", "api_version", "is_portability_driver"}) or
            type(icd["library_path"]) is not str or
            not _LIBRARY.fullmatch(Path(icd["library_path"]).name) or
            ("/" in icd["library_path"] and not any(
                icd["library_path"].startswith(f"{root}/") for root in _SYSTEM_LIBRARY_DIRS)) or
            type(icd["api_version"]) is not str or not _API.fullmatch(icd["api_version"]) or
            icd.get("is_portability_driver", False) not in (False,)):
        raise ValueError("VULKAN_REFERENCE_LVP_ONLY")
    library = _resolve_system_library(icd["library_path"])
    metadata = {
        "path": str(path), "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "library_name": Path(icd["library_path"]).name, "library_path_declared": icd["library_path"],
        "api_version_declared": icd["api_version"],
    }
    icd["library_path"] = str(library)
    return metadata, document


def validate_reference_manifest(path: Path) -> dict:
    """Validate narrow Mesa software ICD reference, not arbitrary user libraries."""
    metadata, _ = _read_reference_manifest(path)
    return metadata


def verify_reference_summary(stdout: str) -> dict:
    """Only interpret an actual caller-provided vulkaninfo summary, never infer GPU identity."""
    types = _DEVICE_TYPE.findall(stdout)
    names = _DEVICE_NAME.findall(stdout)
    if (len(types) != 1 or len(names) != 1 or types[0] != _CPU or
            not ("llvmpipe" in names[0].lower() or "lavapipe" in names[0].lower()) or
            "Ouroboros" in stdout or "ARE SoftwareGPU" in stdout):
        raise ValueError("VULKAN_REFERENCE_CPU_DEVICE_NOT_PROVEN")
    return {"device_type": types[0], "device_name": names[0]}


def run_reference_probe(manifest: Path, *, vulkaninfo: str = "vulkaninfo",
                        source_sha: str = "") -> dict:
    verified_manifest, loader_manifest = _read_reference_manifest(manifest)
    # Fail closed: no privileged Loader override. We intentionally do not
    # install, edit, or register any driver globally.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise PermissionError("VULKAN_REFERENCE_NONROOT_REQUIRED")
    env = os.environ.copy()
    env.pop("VK_ICD_FILENAMES", None)
    env.pop("VK_ADD_DRIVER_FILES", None)
    env.pop("VK_LOADER_DRIVERS_SELECT", None)
    env.pop("VK_LOADER_DRIVERS_DISABLE", None)
    env["VK_LOADER_DEBUG"] = "driver"
    # The loader must read the validated data, not reopen the caller's file.
    with tempfile.TemporaryDirectory(prefix="are-lavapipe-", dir="/tmp") as directory:
        snapshot = Path(directory) / "lvp_icd.json"
        snapshot.write_text(json.dumps(loader_manifest), encoding="utf-8")
        env["VK_DRIVER_FILES"] = str(snapshot)
        result = subprocess.run([vulkaninfo, "--summary"], env=env,
                                capture_output=True, text=True, timeout=45,
                                check=False)
    if result.returncode:
        raise RuntimeError("VULKAN_REFERENCE_LOADER_FAILED:" + str(result.returncode) +
                           ":" + result.stderr[-800:])
    if len(result.stdout) > 131072 or len(result.stderr) > 131072:
        raise ValueError("VULKAN_REFERENCE_OUTPUT_BUDGET")
    observed = verify_reference_summary(result.stdout)
    if "lvp" not in result.stderr.lower() and "lavapipe" not in result.stderr.lower():
        raise RuntimeError("VULKAN_REFERENCE_LOADER_BINDING_NOT_PROVEN")
    receipt = {
        "protocol": "are.vulkan-reference-probe.v1",
        "status": "PASS_REFERENCE_ONLY",
        "source_revision": source_sha or "UNKNOWN",
        "renderer_owner": "Mesa Lavapipe",
        "are_vulkan_icd": False,
        "are_loader_device_verified": False,
        "unity_runtime_verified": False,
        "vulkaninfo_command": [vulkaninfo, "--summary"],
        "returncode": result.returncode,
        "manifest": verified_manifest,
        "observed_device": observed,
        "vulkaninfo_stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "vulkaninfo_stdout": result.stdout,
        "loader_stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        "loader_stderr": result.stderr,
    }
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["receipt_sha256"] = hashlib.sha256(canonical).hexdigest()
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.source_revision):
        parser.error("full 40-digit Git revision required")
    receipt = run_reference_probe(args.manifest, source_sha=args.source_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("VULKAN_LAVAPIPE_REFERENCE_ONLY_PASS " + receipt["receipt_sha256"])


if __name__ == "__main__":
    main()
