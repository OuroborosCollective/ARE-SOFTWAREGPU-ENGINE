"""Real Khronos Vulkan-loader admission for ARE -> Mesa Zink.

Nonzero native probe exit 3 means unsupported Vulkan capabilities, never a
successful OpenGL render. Reject segfaults, non-ARE devices, stale revisions,
missing receipts and inconsistent claims. No Mesa/GLX fallback is accepted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from software_gpu.research.native_symbolic import compiler


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def classify(returncode, record):
    if returncode not in (0, 3):
        raise ValueError("ARE_ZINK_NATIVE_PROBE_UNEXPECTED_EXIT:" + str(returncode))
    if record.get("protocol") != "are.zink-capability-preflight.v1":
        raise ValueError("ARE_ZINK_PROBE_PROTOCOL_MISMATCH")
    if not str(record.get("device", "")).startswith("ARE SoftwareGPU"):
        raise ValueError("ARE_ZINK_NON_ARE_DEVICE_REFUSED")
    if record.get("gl45_and_heaven_verified") is not False:
        raise ValueError("ARE_ZINK_NO_HEAVEN_RENDER_PROVEN")
    extensions = record.get("extensions_advertised")
    features = record.get("missing_gl21_features")
    missing = record.get("missing_gl21_extensions")
    if not all(isinstance(x, list) and all(isinstance(item, str) and item for item in x)
               for x in (extensions, features, missing)):
        raise ValueError("ARE_ZINK_CAPABILITY_ARRAYS_INVALID")
    if "VK_KHR_swapchain" not in extensions:
        raise ValueError("ARE_ZINK_ACTUAL_SWAPCHAIN_REQUIRED")
    if not isinstance(record.get("api_version"), dict):
        raise ValueError("ARE_ZINK_ACTUAL_API_VERSION_REQUIRED")
    if record["api_version"].get("major") != 1:
        raise ValueError("ARE_ZINK_UNKNOWN_VULKAN_API")
    ready = record.get("minimum_gl21_ready")
    if returncode == 0 and ready is True and not features and not missing:
        if record.get("extended_feature_bits_queried") is not True:
            raise ValueError("ARE_ZINK_EXTENSION_FEATURE_BITS_UNVERIFIED")
        return "minimum-vulkan-capabilities"
    if returncode == 3 and ready is False and (features or missing):
        return "incompatible"
    raise ValueError("ARE_ZINK_PROBE_STATUS_CAPABILITIES_CONTRADICTION")


def build_receipt(expected_revision, source, library, manifest, executable,
                  stdout, stderr, native_probe_exit, status, observed):
    """Bind original real-probe bytes and claimed identity to one canonical digest.

    Pure receipt construction; the caller alone performs the real Vulkan run.
    No test data produced here is executable Vulkan or OpenGL evidence.
    """
    report = {
        "protocol": "are.zink-real-preflight-receipt.v1",
        "source_revision": expected_revision,
        "source_sha256": digest(source),
        "driver_sha256": digest(library),
        "manifest_sha256": digest(manifest),
        "probe_executable_sha256": digest(executable),
        "probe_stdout_sha256": digest(stdout),
        "probe_stderr_sha256": digest(stderr),
        "native_probe_exit": native_probe_exit,
        "zink_vulkan_minimum_status": status,
        "real_vulkan_device": observed,
        "real_glx_context_verified": False,
        "real_heaven_score_verified": False,
        "hardware_device_claim": False,
    }
    report["receipt_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return report


def checked_source_at_revision(root, expected_revision, relative_path):
    """Prevent a dirty probe source from being relabeled as committed code."""
    source = root / relative_path
    # Compare the committed Git blob against the working file AFTER Git's
    # own clean/EOL filters. A genuine Windows CRLF checkout is identical
    # to its committed LF blob; semantic changes still fail closed.
    expected_blob = subprocess.check_output(
        ["git", "rev-parse", expected_revision + ":" + relative_path],
        cwd=root, text=True, timeout=15).strip()
    working_blob = subprocess.check_output(
        ["git", "hash-object", "--path=" + relative_path, str(source)],
        cwd=root, text=True, timeout=15).strip()
    if not expected_blob or working_blob != expected_blob:
        raise ValueError("ARE_ZINK_PROBE_SOURCE_TREE_DRIFT")
    return source


def verify(output, manifest, expected_revision, include):
    root = Path(__file__).resolve().parents[2]
    actual_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, cwd=root).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", expected_revision) or actual_revision != expected_revision:
        raise ValueError("ARE_ZINK_SOURCE_REVISION_MISMATCH")
    source = checked_source_at_revision(
        root, expected_revision, "native/vulkan/weighted/opengl_zink_capability_probe.cpp")
    manifest = manifest.resolve(strict=True)
    metadata = json.loads(manifest.read_text())
    library = Path(metadata["ICD"]["library_path"]).resolve(strict=True)
    if not library.is_file() or library.name != "libare_weighted.so":
        raise ValueError("ARE_ZINK_ICD_LIBRARY_IDENTITY_INVALID")
    if metadata["ICD"].get("api_version") != "1.0.0":
        raise ValueError("ARE_ZINK_ICD_PROFILE_MISMATCH")
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("ARE_ZINK_OUTPUT_MUST_BE_EMPTY")
    output.mkdir(parents=True, exist_ok=True)
    executable = output / "are-zink-native-probe"
    subprocess.run([compiler(), "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-I" + str(include), str(source), "-lvulkan", "-o",
                    str(executable)], check=True, timeout=120)
    env = os.environ.copy()
    env["VK_DRIVER_FILES"] = str(manifest)
    env["VK_ICD_FILENAMES"] = str(manifest)
    env["OPENBLAS_NUM_THREADS"] = "1"
    env.pop("PYTHONHOME", None)
    for item in ("VK_ADD_DRIVER_FILES", "VK_LOADER_DRIVERS_SELECT",
                 "VK_LOADER_DRIVERS_DISABLE"):
        env.pop(item, None)
    env["PYTHONPATH"] = os.pathsep.join([str(root), *sys.path])
    run = subprocess.run([str(executable)], env=env, capture_output=True,
                         timeout=30)
    (output / "stdout.json").write_bytes(run.stdout)
    (output / "stderr.txt").write_bytes(run.stderr)
    try:
        observed = json.loads(run.stdout)
    except (ValueError, UnicodeError) as e:
        raise ValueError("ARE_ZINK_NATIVE_JSON_INVALID") from e
    status = classify(run.returncode, observed)
    report = build_receipt(
        expected_revision, source, library, manifest, executable,
        output / "stdout.json", output / "stderr.txt",
        run.returncode, status, observed)
    (output / "receipt.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output", type=Path)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--expected-revision", required=True)
    ap.add_argument("--include", type=Path, default=Path("/usr/include"))
    args = ap.parse_args()
    print(json.dumps(verify(args.output, args.manifest,
                            args.expected_revision, args.include), indent=2))
