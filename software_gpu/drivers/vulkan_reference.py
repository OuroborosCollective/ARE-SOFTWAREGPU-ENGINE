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
_DEVICE_TYPE = re.compile(r"^\s*deviceType\s*=\s*([A-Z_0-9]+)\s*$", re.MULTILINE)
_DEVICE_NAME = re.compile(r"^\s*deviceName\s*=\s*(.*?)\s*$", re.MULTILINE)


_SYSTEM_LIB_DIRS = tuple(map(Path, ("/usr/lib", "/lib", "/usr/lib64", "/lib64")))


def _trusted_library(declared: str, manifest_dir: Path) -> Path:
    if os.name != "posix":
        raise ValueError("VULKAN_REFERENCE_SYSTEM_LIBRARY_REQUIRED")
    if "/" in declared:
        candidates = [manifest_dir / declared]
    else:
        # Pin bare sonames to a distribution directory, independent of ld.so search overrides.
        multiarch = sysconfig.get_config_var("MULTIARCH")
        dirs = [root / multiarch for root in _SYSTEM_LIB_DIRS] if multiarch else []
        candidates = [directory / declared for directory in (*dirs, *_SYSTEM_LIB_DIRS)]
    for candidate in candidates:
        try:
            library = candidate.resolve(strict=True)
        except FileNotFoundError:
            continue
        if not _LIBRARY.fullmatch(library.name) or not any(
                root in library.parents for root in _SYSTEM_LIB_DIRS):
            continue
        # Check from the filesystem root down: each protected parent anchors the next lookup.
        for entry in (*reversed(library.parents), library):
            info = entry.lstat()
            kind = stat.S_ISREG if entry == library else stat.S_ISDIR
            if info.st_uid != 0 or info.st_mode & 0o022 or not kind(info.st_mode):
                break
        else:
            return library
    raise ValueError("VULKAN_REFERENCE_SYSTEM_LIBRARY_REQUIRED")


def validate_reference_manifest(path: Path) -> dict:
    """Validate narrow Mesa software ICD reference, not arbitrary user libraries."""
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
            type(icd["api_version"]) is not str or not _API.fullmatch(icd["api_version"]) or
            icd.get("is_portability_driver", False) not in (False,)):
        raise ValueError("VULKAN_REFERENCE_LVP_ONLY")
    return {
        "path": str(path), "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "library_name": Path(icd["library_path"]).name, "library_path_declared": icd["library_path"],
        "library_path_resolved": str(_trusted_library(icd["library_path"], path.parent)),
        "file_format_version": document["file_format_version"],
        "api_version_declared": icd["api_version"],
    }


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
    verified_manifest = validate_reference_manifest(manifest)
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
    # The caller owns the input manifest. Give the loader only validated fields
    # and the absolute, protected library path in a private manifest.
    with tempfile.TemporaryDirectory(prefix="are-lvp-", dir="/tmp") as directory:
        pinned = Path(directory) / "lvp_icd.json"
        pinned.write_text(json.dumps({
            "file_format_version": verified_manifest["file_format_version"],
            "ICD": {"library_path": verified_manifest["library_path_resolved"],
                    "api_version": verified_manifest["api_version_declared"]},
        }), encoding="utf-8")
        env["VK_DRIVER_FILES"] = str(pinned)
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
