"""Real Vulkan loader admission for ARE *zero-device* ICD canary.

Compiles actual ARE C++17 raster adapter into the same ICD library, then uses
the real Khronos system loader to create/destroy an instance and enumerate
ZERO physical devices. Zero is the only truthful count before working Vulkan
VkDevice/queue/resource/shader/command functionality. No system registration.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from software_gpu.drivers.native_bridge import DriverCapabilitiesV1
from software_gpu.research.native_symbolic import FLAGS, compiler


def hashfile(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(expected_revision: str) -> dict:
    source_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip()
    if not expected_revision or source_revision != expected_revision:
        raise RuntimeError("ARE_ICD_CANARY_REVISION_MISMATCH")
    project = Path(__file__).resolve().parents[2]
    source_paths = (
        "native/vulkan/are_loader_canary.cpp",
        "native/vulkan/loader_canary_probe.cpp",
        "native/raster/driver_adapter.cpp",
        "native/raster/driver_adapter.hpp",
        "native/raster/core.hpp",
        "native/symbolic/core.hpp",
    )
    source_hashes = {name: hashfile(project / name) for name in source_paths}
    with tempfile.TemporaryDirectory(prefix="are-vulkan-icd-canary-") as rootname:
        root = Path(rootname)
        library = root / "libare_loader_canary.so"
        executable = root / "loader-probe"
        command = [compiler(), *FLAGS, "-shared", "-fPIC",
                   str(project / "native/vulkan/are_loader_canary.cpp"),
                   str(project / "native/raster/driver_adapter.cpp"),
                   "-o", str(library)]
        built = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise RuntimeError("ARE_ICD_REAL_NATIVE_BUILD_FAILED:" + built.stderr[-5000:])
        probe_build = subprocess.run([
            compiler(), *FLAGS, str(project / "native/vulkan/loader_canary_probe.cpp"),
            "-o", str(executable), "-lvulkan"
        ], capture_output=True, text=True, timeout=120)
        if probe_build.returncode:
            raise RuntimeError("ARE_ICD_PROBE_BUILD_FAILED:" + probe_build.stderr[-5000:])

        native = ctypes.CDLL(str(library))
        native.are_driver_abi.restype = ctypes.c_uint32
        if native.are_driver_abi() != 1:
            raise RuntimeError("ARE_ICD_NOT_LINKED_TO_NATIVE_ARE_DRIVER")
        caps = DriverCapabilitiesV1()
        native.are_driver_capabilities_v1.argtypes = [
            ctypes.POINTER(DriverCapabilitiesV1), ctypes.c_size_t
        ]
        native.are_driver_capabilities_v1.restype = ctypes.c_int
        if (native.are_driver_capabilities_v1(ctypes.byref(caps), ctypes.sizeof(caps)) != 0
                or caps.device_kind != 1 or caps.supports_vulkan_icd != 0
                or caps.supports_spirv != 0 or caps.supports_wsi != 0):
            raise RuntimeError("ARE_ICD_CANARY_CAPABILITY_LIE")
        negotiate = native.vk_icdNegotiateLoaderICDInterfaceVersion
        negotiate.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
        negotiate.restype = ctypes.c_int32
        version = ctypes.c_uint32(7)
        if negotiate(ctypes.byref(version)) != 0 or version.value != 5:
            raise RuntimeError("ARE_ICD_LOADER_INTERFACE_VERSION_INVALID")
        low = ctypes.c_uint32(1)
        if negotiate(ctypes.byref(low)) == 0:
            raise RuntimeError("ARE_ICD_LOADER_INTERFACE_ACCEPTED_UNSUPPORTED")

        manifest = root / "are-canary-icd.json"
        manifest.write_text(json.dumps({
            "file_format_version": "1.0.0",
            "ICD": {"library_path": str(library), "api_version": "1.0.0"}
        }, sort_keys=True) + "\n", encoding="utf-8")
        env = dict(os.environ)
        for key in ("VK_ICD_FILENAMES", "VK_ADD_DRIVER_FILES",
                    "VK_LOADER_DRIVERS_SELECT", "VK_LOADER_DRIVERS_DISABLE"):
            env.pop(key, None)
        env["VK_DRIVER_FILES"] = str(manifest)
        env["VK_LOADER_DEBUG"] = "driver"
        env["ARE_ICD_TRACE"] = "1"  # Actual ICD entries invoked by system loader only
        observed = subprocess.run([str(executable)], env=env,
                                  capture_output=True, text=True, timeout=30)
        if (observed.returncode != 0 or
                "ARE_REAL_LOADER_ENUMERATION_RESULT=0 COUNT=0" not in observed.stdout):
            raise RuntimeError("ARE_ICD_REAL_LOADER_REJECTED:" +
                               observed.stdout[-1000:] + observed.stderr[-2000:])
        if library.name not in observed.stderr:
            raise RuntimeError("ARE_ICD_REAL_LOADER_LIBRARY_BINDING_UNPROVEN")
        return {
            "protocol": "are.vulkan-loader-zero-device-admission.v1",
            "status": "PASS_REAL_LOADER_ZERO_PHYSICAL_DEVICES",
            "source_revision": source_revision,
            "source_sha256": source_hashes,
            "driver_binary_sha256": hashfile(library),
            "probe_binary_sha256": hashfile(executable),
            "manifest_sha256": hashfile(manifest),
            "actual_vk_create_instance": True,
            "actual_vk_enumerate_physical_devices": True,
            "enumerated_devices": 0,
            "are_cpp_driver_abi": 1,
            "negotiated_loader_interface": version.value,
            "loader_stdout_sha256": hashlib.sha256(observed.stdout.encode()).hexdigest(),
            "loader_stderr_sha256": hashlib.sha256(observed.stderr.encode()).hexdigest(),
            "are_vulkan_physical_device": False,
            "are_vulkan_rendering": False,
            "vulkan_wsi": False,
            "unity_runtime": False,
            "learning_eligible": False,
            "next_required": "Real VkDevice, resources, command/queue, shader and raster before GPU enumeration",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.expected_revision)
    checksum = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    report["receipt_sha256"] = checksum
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("ARE_REAL_LOADER_ZERO_DEVICE_PASS " + checksum)


if __name__ == "__main__":
    main()
