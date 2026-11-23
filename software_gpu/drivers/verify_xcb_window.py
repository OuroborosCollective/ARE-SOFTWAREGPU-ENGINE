"""Exact-source real X server window readback from the native ARE C++ raster.

This is NOT Vulkan VkSurfaceKHR/VkSwapchainKHR support. Requires real Xvfb or
a separate existing X server. Does not modify the running Unity display.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from software_gpu.research.native_symbolic import FLAGS, compiler

WIDTH, HEIGHT = 32, 24


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(expected_revision: str, out: Path) -> dict:
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", expected_revision) or git_head != expected_revision:
        raise RuntimeError("ARE_XCB_SOURCE_SHA_MISMATCH")
    if not os.environ.get("DISPLAY"):
        raise RuntimeError("ARE_XCB_REAL_XSERVER_REQUIRED")
    root = Path(__file__).resolve().parents[2]
    source_paths = (
        "native/vulkan/xcb_present.hpp",
        "native/vulkan/xcb_present_probe.cpp",
        "native/raster/driver_adapter.cpp",
        "native/raster/driver_adapter.hpp",
        "native/raster/core.hpp",
        "native/symbolic/core.hpp",
    )
    hashes = {name: sha(root / name) for name in source_paths}
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="are-xcb-") as work:
        binary = Path(work) / "are-real-xcb-window"
        command = [compiler(), *FLAGS, "-Werror",
                   str(root / "native/vulkan/xcb_present_probe.cpp"),
                   str(root / "native/raster/driver_adapter.cpp"),
                   "-lxcb", "-o", str(binary)]
        build = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if build.returncode:
            raise RuntimeError("ARE_XCB_CPP_BUILD_FAILED:" + build.stderr[-6000:])
        real_paths = [out / n for n in (
            "are_rgba_red.bin", "are_rgba_green.bin",
            "xcb_window_red.bin", "xcb_window_green.bin",
        )]
        run = subprocess.run([str(binary), *(str(x) for x in real_paths)],
                             capture_output=True, text=True, timeout=35)
        if run.returncode or not run.stdout.startswith("ARE_REAL_XCB_WINDOW_READBACK_PASS "):
            raise RuntimeError("ARE_XCB_REAL_WINDOW_FAILED:" +
                               run.stdout[-1500:] + run.stderr[-1500:])
        tokens = run.stdout.split()
        if len(tokens) != 4:
            raise RuntimeError("ARE_XCB_COUNTER_FORMAT")
        counts = [int(v) for v in tokens[1:]]
        if not counts[0] >= counts[1] >= counts[2] > 0:
            raise RuntimeError("ARE_XCB_NATIVE_SAMPLE_PROOF")
        raw = [p.read_bytes() for p in real_paths]
        if any(len(data) != WIDTH * HEIGHT * 4 for data in raw):
            raise RuntimeError("ARE_XCB_FRAME_DIMENSION")
        for src, observed in ((raw[0],raw[2]),(raw[1],raw[3])):
            for j in range(WIDTH * HEIGHT):
                if (observed[4*j:4*j+3] !=
                    bytes((src[4*j+2],src[4*j+1],src[4*j]))):
                    raise RuntimeError("ARE_XCB_EXTERNAL_PIXEL_MISMATCH")
        if raw[0] == raw[1] or raw[2] == raw[3]:
            raise RuntimeError("ARE_XCB_FRAMES_IDENTICAL")
        inside = (4 * WIDTH + 4) * 4
        if raw[0][inside:inside+3] != bytes((255,0,0)):
            raise RuntimeError("ARE_XCB_EXPECTED_NATIVE_RED_PIXEL_MISSING")
        if raw[1][inside:inside+3] != bytes((0,255,0)):
            raise RuntimeError("ARE_XCB_EXPECTED_NATIVE_GREEN_PIXEL_MISSING")
        neg = subprocess.run([str(binary),*(str(Path(work) / ("bad"+str(i)))
                                            for i in range(4))],
                             env={**os.environ, "DISPLAY": ":4094"},
                             capture_output=True, text=True, timeout=8)
        if neg.returncode == 0:
            raise RuntimeError("ARE_XCB_INVALID_DISPLAY_NOT_REJECTED")
        return {
            "protocol": "are.real-xcb-window-readback.v1",
            "status": "REAL_ARE_CPU_PIXELS_IN_XCB_WINDOW_PASS",
            "source_revision": expected_revision,
            "native_sources_sha256": hashes,
            "cpp_binary_sha256": sha(binary),
            "frame_rgba_red_sha256": sha(real_paths[0]),
            "frame_rgba_green_sha256": sha(real_paths[1]),
            "real_xcb_window_red_sha256": sha(real_paths[2]),
            "real_xcb_window_green_sha256": sha(real_paths[3]),
            "window_resolution": [WIDTH,HEIGHT],
            "candidate_samples": counts[0],
            "covered_samples": counts[1],
            "shaded_samples": counts[2],
            "frame_color_parity_via_real_xcb_server": True,
            "invalid_display_rejected": True,
            "vulkan_icd": False,
            "vkphysicaldevice": False,
            "vksurface": False,
            "vkswapchain": False,
            "vkqueuepresent": False,
            "unity_runtime": False,
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected-revision", required=True)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    receipt = verify(args.expected_revision, args.output)
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (args.output / "receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("ARE_REAL_XCB_WINDOW_READBACK_PASS " + receipt["receipt_sha256"])


if __name__ == "__main__":
    main()
