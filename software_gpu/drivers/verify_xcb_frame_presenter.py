"""Real X11 pixel readback of ARE native CPU raster frames under isolated Xvfb.

This bridge is NOT VK_KHR_surface, VK_KHR_xcb_surface, VK_KHR_swapchain,
VkQueuePresentKHR, or proof of a Unity-compatible Vulkan driver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from software_gpu.research.native_symbolic import FLAGS, compiler


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(expected_revision: str) -> dict:
    root = Path(__file__).resolve().parents[2]
    observed = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                       text=True).strip()
    if not re.fullmatch("[0-9a-f]{40}", expected_revision) or observed != expected_revision:
        raise RuntimeError("ARE_XCB_SOURCE_REVISION_MISMATCH")
    source_paths = (
        "native/vulkan/xcb_frame_presenter.hpp",
        "native/vulkan/xcb_frame_presenter_test.cpp",
        "native/raster/driver_adapter.cpp",
        "native/raster/driver_adapter.hpp",
        "native/raster/core.hpp",
        "native/symbolic/core.hpp",
    )
    source_digests = {p:sha256(root/p) for p in source_paths}
    with tempfile.TemporaryDirectory(prefix="are-real-xcb-") as directory:
        work = Path(directory)
        binary = work / "are-xcb-real-test"
        cmd = [compiler(), *FLAGS,
               str(root/"native/vulkan/xcb_frame_presenter_test.cpp"),
               str(root/"native/raster/driver_adapter.cpp"),
               "-lxcb", "-o", str(binary)]
        compiled = subprocess.run(cmd,capture_output=True,text=True,timeout=120)
        if compiled.returncode:
            raise RuntimeError("ARE_XCB_CXX_BUILD_FAILED:"+compiled.stderr[-6500:])
        no_display = os.environ.copy()
        no_display.pop("DISPLAY",None)
        no_display.pop("XAUTHORITY",None)
        negative = subprocess.run([str(binary),"--negative-no-display"],
                                  env=no_display,capture_output=True,text=True,timeout=20)
        if negative.returncode:
            raise RuntimeError("ARE_XCB_NO_DISPLAY_NEGATIVE_FAILED:"+negative.stderr[-2000:])
        output_base = work/"captured"
        actual = subprocess.run([
            "xvfb-run","-a","-s","-screen 0 640x480x24",
            str(binary),str(output_base),
        ],capture_output=True,text=True,timeout=70)
        if actual.returncode or not actual.stdout.startswith("ARE_XCB_REAL_NATIVE_FRAME_PASS "):
            raise RuntimeError("ARE_XCB_REAL_WINDOW_FAILED:"+actual.stdout[-900:]+actual.stderr[-2400:])

        names = ["first","second","resize"]
        dimensions = {"first":(32,24),"second":(32,24),"resize":(64,48)}
        results = {}
        for label in names:
            cpu = Path(str(output_base)+f"-{label}-cpu.rgba")
            window = Path(str(output_base)+f"-{label}-window.rgba")
            dim = dimensions[label]
            expected_size = dim[0]*dim[1]*4
            if (cpu.stat().st_size != expected_size or
                window.stat().st_size != expected_size or
                cpu.read_bytes() != window.read_bytes()):
                raise RuntimeError("ARE_XCB_SCREEN_RASTER_PARITY:"+label)
            raw = cpu.read_bytes()
            if all(v==0 for i,v in enumerate(raw) if i%4 != 3):
                raise RuntimeError("ARE_XCB_BLACK_FRAME:"+label)
            if any(raw[i]!=255 for i in range(3,len(raw),4)):
                raise RuntimeError("ARE_XCB_ALPHA_BACKGROUND_CONTRACT:"+label)
            results[label]={"width":dim[0],"height":dim[1],
                            "native_rgba_sha256":sha256(cpu),
                            "xcb_window_readback_sha256":sha256(window),
                            "bytes":expected_size}
        if results["first"]["native_rgba_sha256"] == results["second"]["native_rgba_sha256"]:
            raise RuntimeError("ARE_XCB_TWO_REAL_FRAMES_NOT_DISTINCT")
        return {
            "protocol":"are.xcb-cpu-presentation-prewsi.v1",
            "status":"REAL_XCB_PIXEL_READBACK_MATCHES_REAL_ARE_NATIVE_RASTER",
            "source_revision":observed,
            "source_sha256":source_digests,
            "native_binary_sha256":sha256(binary),
            "actual_xcb_put_image_and_get_image":True,
            "real_isolated_xvfb":True,
            "invalid_extent_and_payload_rejected":True,
            "real_resize_and_old_extent_rejection":True,
            "missing_display_rejected":True,
            "frames":results,
            "vulkan_wsi_extension_available":False,
            "vk_surface_khr":False,
            "vk_swapchain_khr":False,
            "vk_queue_present_khr":False,
            "unity_runtime_verified":False,
        }


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--expected-revision",required=True)
    ap.add_argument("--output",required=True,type=Path)
    args=ap.parse_args()
    receipt=verify(args.expected_revision)
    receipt["receipt_sha256"]=hashlib.sha256(json.dumps(
        receipt,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print("ARE_XCB_REAL_PRESENTATION_GATE_PASS "+receipt["receipt_sha256"])


if __name__=="__main__":
    main()
