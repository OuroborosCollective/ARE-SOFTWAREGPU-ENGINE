"""Real ARE Vulkan QueueSubmit -> XCB Swapchain/Present -> X Server readback.

Only the limited experimental Vulkan 1.0 profile is admitted. Not a Unity,
Wayland, Windows, full CTS, or system-driver certification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
from software_gpu.drivers.build_weighted_icd import build
from software_gpu.research.native_symbolic import compiler


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(out, expected_revision, registry, include):
    root = Path(__file__).resolve().parents[2]
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if not re.fullmatch("[0-9a-f]{40}", expected_revision) or expected_revision != actual:
        raise RuntimeError("ARE_WSI_SOURCE_REVISION_MISMATCH")
    out = out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError("ARE_WSI_REQUIRE_EMPTY_OUTPUT")
    out.mkdir(parents=True, exist_ok=True)
    bundle = out / "icd"
    manifest = build(bundle, registry, include)
    library = bundle / "libare_weighted.so"
    probes = {}
    for name in ("wsi_probe", "wsi_draw_probe"):
        path = out / name
        subprocess.run([compiler(), "-std=c++17", "-I" + str(include),
                        str(root / "native/vulkan/weighted" / (name + ".cpp")),
                        "-lvulkan", "-lxcb", "-o", str(path)],
                       check=True, timeout=120)
        probes[name] = path
    env = os.environ.copy()
    env.update(VK_DRIVER_FILES=str(manifest), VK_ICD_FILENAMES=str(manifest),
               VK_LOADER_DEBUG="all", OPENBLAS_NUM_THREADS="1",
               ARE_LEARNING_DB=str(out / "learning.sqlite3"),
               ARE_VK_RECEIPTS=str(out / "submissions.jsonl"))
    for name in ("VK_ADD_DRIVER_FILES", "VK_LOADER_DRIVERS_SELECT",
                 "VK_LOADER_DRIVERS_DISABLE", "PYTHONHOME"):
        env.pop(name, None)
    env["PYTHONPATH"] = os.pathsep.join([str(root), *[p for p in sys.path if p]])

    def run(name, args, *, success=True, display=True):
        command = (["xvfb-run", "-a", "-s", "-screen 0 256x256x24"] if display else []) + args
        parameters = env.copy()
        if not display:
            parameters.pop("DISPLAY", None)
            parameters.pop("XAUTHORITY", None)
        result = subprocess.run(command, env=parameters, capture_output=True, timeout=120)
        (out / (name + ".stdout")).write_bytes(result.stdout)
        (out / (name + ".stderr")).write_bytes(result.stderr)
        if (result.returncode == 0) != success:
            raise RuntimeError("ARE_WSI_" + name + "_EXIT:" + str(result.returncode) +
                               ":" + repr(result.stderr[-1400:]))
        return result

    no_display = run("no-display",
                     [str(probes["wsi_draw_probe"]), str(bundle), str(out / "absent")],
                     success=False, display=False)
    if b"No real XCB connection" not in no_display.stderr:
        raise RuntimeError("ARE_WSI_NO_DISPLAY_NOT_REJECTED")
    surface = run("real-surface", [str(probes["wsi_probe"])])
    if (b"ARE_REAL_VULKAN_XCB_SURFACE_PASS" not in surface.stdout or
            b"ARE SoftwareGPU" not in surface.stdout):
        raise RuntimeError("ARE_WSI_TRUE_ARE_DEVICE_SURFACE_REQUIRED")
    x, y = np.meshgrid((np.arange(32) + .5) / 32, (np.arange(24) + .5) / 24)
    covered = x + y < 1
    rgb = np.stack((1-x-y, x, y), axis=-1) * 255
    frames = {}
    for name in ("A", "B"):
        destination = out / ("frame-" + name)
        arguments = [str(probes["wsi_draw_probe"]), str(bundle), str(destination)]
        if name == "B":
            arguments.append("rgb-cycle")
        run("draw-" + name, arguments)
        rgba_file, depth_file = destination.with_suffix(".rgba"), destination.with_suffix(".depth")
        rgba = np.fromfile(rgba_file, np.uint8).reshape(24, 32, 4)
        depth = np.fromfile(depth_file, np.float32).reshape(24, 32)
        expected = rgb if name == "A" else rgb[:, :, (2, 0, 1)]
        if (not np.array_equal(depth, np.where(covered, .5, 1.).astype(np.float32)) or
                not np.all(rgba[:, :, 3] == 255) or np.any(rgba[~covered, :3]) or
                np.max(np.abs(expected[covered] -
                              rgba[covered, :3].astype(np.float64))) > 1.001):
            raise RuntimeError("ARE_WSI_INDEPENDENT_REAL_PIXELS_DEPTH_MISMATCH:" + name)
        frames[name] = dict(rgba_sha256=sha(rgba_file), depth_sha256=sha(depth_file),
                            visible_pixels=int(covered.sum()), rgba_bytes=rgba_file.stat().st_size)
    if (frames["A"]["rgba_sha256"] == frames["B"]["rgba_sha256"] or
            frames["A"]["depth_sha256"] != frames["B"]["depth_sha256"]):
        raise RuntimeError("ARE_WSI_DISTINCT_FRAMES_PARITY_REQUIRED")
    events = [json.loads(line) for line in (out / "submissions.jsonl").read_text().splitlines()]
    draws = [v for v in events if v.get("event") == "vkQueueSubmit/graphics"]
    presents = [v for v in events if v.get("event") == "vkQueuePresentKHR/xcb-native"]
    if len(draws) != 2 or len(presents) != 2:
        raise RuntimeError("ARE_WSI_REAL_VULKAN_SUBMIT_PRESENT_PAIR_REQUIRED")
    for i, name in enumerate(("A", "B")):
        f = frames[name]
        d, p = draws[i], presents[i]
        if (d["driver_sha256"] != sha(library) or
                p["driver_sha256"] != sha(library) or
                d["native_submission"]["rgba_sha256"] != f["rgba_sha256"] or
                d["native_submission"]["depth_sha256"] != f["depth_sha256"] or
                d["native_submission"]["shaded_samples"] != f["visible_pixels"] or
                p["vk_image_sha256"] != f["rgba_sha256"] or
                p["xcb_get_image_sha256"] != f["rgba_sha256"]):
            raise RuntimeError("ARE_WSI_NATIVE_DRIVER_AND_WINDOW_DIGEST_MISMATCH:" + name)
    sources = ("native/vulkan/weighted/entry.cpp",
               "native/vulkan/weighted/xcb_wsi.cpp",
               "native/vulkan/weighted/wsi_probe.cpp",
               "native/vulkan/weighted/wsi_draw_probe.cpp",
               "software_gpu/drivers/weighted_icd.py",
               "software_gpu/drivers/build_weighted_icd.py",
               "software_gpu/drivers/verify_weighted_wsi.py",
               "native/raster/driver_adapter.cpp")
    report = dict(protocol="are.vulkan.xcb-native-wsi.v1",
                  source_revision=actual,
                  source_sha256={name:sha(root / name) for name in sources},
                  library_sha256=sha(library),
                  manifest_sha256=sha(manifest),
                  probe_sha256={name:sha(path) for name,path in probes.items()},
                  frames=frames,
                  real_vulkan_device_queue_submit=True,
                  real_xcb_surface_and_swapchain=True,
                  actual_vk_queue_present_khr=True,
                  independent_xcb_get_image_parity=True,
                  invalid_window_and_present_before_render_rejected=True,
                  resize_out_of_date_rejected=True,
                  no_display_rejected=True,
                  unity_player_verified=False,
                  vulkan_cts_verified=False,
                  limited_vulkan_1_0_profile=True)
    report["receipt_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (out / "receipt.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--expected-revision", required=True)
    p.add_argument("--registry", type=Path,
                   default=Path("/usr/share/vulkan/registry/vk.xml"))
    p.add_argument("--include", type=Path, default=Path("/usr/include"))
    args = p.parse_args()
    print(json.dumps(verify(args.output,args.expected_revision,args.registry,args.include),
                     indent=2))
