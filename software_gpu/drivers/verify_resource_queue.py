"""Verify genuine ARE C++17 owned-buffer submission before Vulkan device export.

Actual program compiles C++ resource queue and links the canonical ARE C ABI.
It compares its native ordered draws to independent real ABI calls and replay,
including a late malformed-draw rollback. No VkDevice or SPIR-V is claimed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from software_gpu.research.native_symbolic import FLAGS, compiler


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(revision: str) -> dict:
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or source != revision:
        raise RuntimeError("ARE_PREDEVICE_SOURCE_REVISION_MISMATCH")
    root = Path(__file__).resolve().parents[2]
    paths = (
        "native/vulkan/resource_queue.hpp",
        "native/vulkan/resource_queue_test.cpp",
        "native/raster/driver_adapter.cpp",
        "native/raster/driver_adapter.hpp",
        "native/raster/core.hpp",
        "native/symbolic/core.hpp",
    )
    source_hashes = {p: digest(root / p) for p in paths}
    with tempfile.TemporaryDirectory(prefix="are-predevice-native-") as tmp:
        target = Path(tmp)
        binary = target / ("are-resource-test.exe" if sys.platform == "win32" else "are-resource-test")
        command = [compiler(), *FLAGS,
                   str(root / "native/vulkan/resource_queue_test.cpp"),
                   str(root / "native/raster/driver_adapter.cpp"),
                   "-o", str(binary)]
        built = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise RuntimeError("ARE_PREDEVICE_NATIVE_BUILD_FAILED:" + built.stderr[-6000:])
        color = target / "rgba.bin"
        depth = target / "depth.bin"
        run = subprocess.run([str(binary),str(color),str(depth)],
                             capture_output=True, text=True, timeout=45)
        if run.returncode or not run.stdout.startswith("ARE_PREDEVICE_REAL_CPP_RASTER_PASS "):
            raise RuntimeError("ARE_PREDEVICE_NATIVE_RUNTIME_FAILED:" +
                               run.stdout[-1200:] + run.stderr[-1200:])
        counts = run.stdout.strip().split()
        if len(counts) != 4:
            raise RuntimeError("ARE_PREDEVICE_COUNTER_FORMAT")
        candidate, covered, shaded = (int(x) for x in counts[1:])
        if not (candidate >= covered >= shaded > 0):
            raise RuntimeError(f"ARE_PREDEVICE_COUNTER_CONTRACT:{candidate}:{covered}:{shaded}")
        if color.stat().st_size != 32 * 24 * 4 or depth.stat().st_size != 32 * 24 * 4:
            raise RuntimeError("ARE_PREDEVICE_FRAME_SIZE")
        return {
            "protocol": "are.predevice-resource-queue-evidence.v1",
            "status": "PASS_REAL_CPP_NATIVE_RESOURCE_QUEUE",
            "source_revision": revision,
            "sources_sha256": source_hashes,
            "binary_sha256": digest(binary),
            "rgba_sha256": digest(color),
            "depth_sha256": digest(depth),
            "resolution": [32,24],
            "candidate_samples": candidate,
            "covered_samples": covered,
            "shaded_samples": shaded,
            "native_cpp_reference_parity": True,
            "native_replay_color_depth_equal": True,
            "native_late_error_rollback": True,
            "resource_handle_and_budget_negative_tests": True,
            "vulkan_loader_device": False,
            "vkdevice": False,
            "vkqueuesubmit": False,
            "vulkan_shaders": False,
            "unity_runtime": False,
            "vulkan_learned_weights": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = verify(args.expected_revision)
    data["receipt_sha256"] = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("ARE_PREDEVICE_REAL_CPP_PASS " + data["receipt_sha256"])


if __name__ == "__main__":
    main()
