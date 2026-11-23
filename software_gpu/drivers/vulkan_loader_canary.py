"""Real libvulkan loader probe for the experimental ARE zero-device ICD.

This is an *incomplete* ICD canary, not a functioning Vulkan graphics device.
Only an external Khronos loader call proves loader discovery; direct symbol
lookup is an additional ABI check and is not a substitute.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


class VkApplicationInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32), ("pNext", ctypes.c_void_p),
        ("pApplicationName", ctypes.c_char_p), ("applicationVersion", ctypes.c_uint32),
        ("pEngineName", ctypes.c_char_p), ("engineVersion", ctypes.c_uint32),
        ("apiVersion", ctypes.c_uint32),
    ]


class VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32), ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32), ("pApplicationInfo", ctypes.POINTER(VkApplicationInfo)),
        ("enabledLayerCount", ctypes.c_uint32), ("ppEnabledLayerNames", ctypes.c_void_p),
        ("enabledExtensionCount", ctypes.c_uint32), ("ppEnabledExtensionNames", ctypes.c_void_p),
    ]


def _actual_loader_calls(library_path: Path) -> dict:
    # A genuine system Vulkan loader is mandatory; no dummy ctypes CDLL for libvulkan.
    vulkan = ctypes.CDLL("libvulkan.so.1")
    vulkan.vkCreateInstance.argtypes = [
        ctypes.POINTER(VkInstanceCreateInfo), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    vulkan.vkCreateInstance.restype = ctypes.c_int32
    vulkan.vkEnumeratePhysicalDevices.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
    ]
    vulkan.vkEnumeratePhysicalDevices.restype = ctypes.c_int32
    vulkan.vkDestroyInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    vulkan.vkDestroyInstance.restype = None
    app = VkApplicationInfo(0, None, b"ARE-real-loader-zero-device-canary", 1,
                            b"ARE", 1, (1 << 22))
    info = VkInstanceCreateInfo(1, None, 0, ctypes.pointer(app), 0, None, 0, None)
    instance = ctypes.c_void_p()
    created = vulkan.vkCreateInstance(ctypes.byref(info), None, ctypes.byref(instance))
    if created != 0 or not instance.value:
        raise RuntimeError(f"ARE_LOADER_VK_CREATE_INSTANCE_FAILED:{created}")
    try:
        # Prove the system Vulkan Loader actually mapped the selected ARE
        # library before ctypes loads the ICD directly. An on-disk manifest
        # and direct symbol lookup do not prove Khronos Loader integration.
        mapped = Path("/proc/self/maps").read_text(encoding="utf-8", errors="replace")
        if str(library_path) not in mapped:
            raise RuntimeError("ARE_LOADER_DID_NOT_MAP_SELECTED_ICD")
        count = ctypes.c_uint32(0xFFFFFFFF)
        enumerated = vulkan.vkEnumeratePhysicalDevices(
            instance, ctypes.byref(count), None
        )
        # On this real Loader a zero-device ICD returns -3
        # (VK_ERROR_INITIALIZATION_FAILED), preserving the input count.
        # Never misreport that result as successful enumeration.
        if enumerated not in (0, -3):
            raise RuntimeError(f"ARE_LOADER_VK_ENUMERATE_UNEXPECTED:{enumerated}")
        if enumerated == 0 and count.value != 0:
            raise RuntimeError(f"ARE_ZERO_DEVICE_CONTRACT_VIOLATED:{count.value}")
        if enumerated == -3 and count.value != 0xFFFFFFFF:
            raise RuntimeError("ARE_ZERO_DEVICE_ERROR_COUNT_CHANGED")
        return {
            "vkCreateInstance": int(created),
            "are_icd_library_mapped_by_real_loader": True,
            "vkEnumeratePhysicalDevices": int(enumerated),
            "physical_device_count": int(count.value) if enumerated == 0 else None,
            "enumeration_completed_successfully": enumerated == 0,
            "no_device_error_observed": enumerated == -3,
        }
    finally:
        vulkan.vkDestroyInstance(instance, None)


def verify_loader(binary: Path, manifest: Path, revision: str) -> dict:
    if not re.fullmatch("[a-f0-9]{40}", revision):
        raise ValueError("ARE_LOADER_SOURCE_REVISION")
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if current != revision:
        raise RuntimeError("ARE_LOADER_SOURCE_CHANGED")
    binary = binary.resolve(strict=True)
    manifest = manifest.resolve(strict=True)
    source = (Path(__file__).resolve().parents[2] / "native/vulkan/loader_canary.cpp")
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    if (manifest_data.get("file_format_version") != "1.0.0" or
            manifest_data.get("ICD", {}).get("library_path") != str(binary) or
            manifest_data.get("ICD", {}).get("api_version") != "1.0.0"):
        raise ValueError("ARE_LOADER_MANIFEST_SOURCE_BINDING")
    # Loader environment has to be established before libvulkan is mapped.
    # Caller must invoke this process with an isolated VK_DRIVER_FILES.
    if (os.environ.get("VK_DRIVER_FILES") != str(manifest) or
            os.environ.get("VK_ICD_FILENAMES") or
            os.environ.get("VK_ADD_DRIVER_FILES")):
        raise RuntimeError("ARE_LOADER_DRIVER_ISOLATION_REQUIRED")
    observed = _actual_loader_calls(binary)
    # Separate direct ABI check after actual Loader/ELF mapping proof.
    lib = ctypes.CDLL(str(binary))
    lib.vk_icdNegotiateLoaderICDInterfaceVersion.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
    lib.vk_icdNegotiateLoaderICDInterfaceVersion.restype = ctypes.c_int32
    version = ctypes.c_uint32(2)
    if lib.vk_icdNegotiateLoaderICDInterfaceVersion(ctypes.byref(version)) != 0 or version.value != 2:
        raise RuntimeError("ARE_LOADER_INTERFACE_NEGOTIATION_FAILED")
    rec = {
        "protocol": "are.vulkan-loader-canary.v1",
        "source_revision": revision,
        "status": "REAL_LOADER_INSTANCE_ACCEPTED_NO_DEVICE_ADVERTISED",
        "driver_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "driver_cpp_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "icd_negotiated_version_direct": version.value,
        "actual_vulkan_loader_calls": observed,
        "device_vendor": "NONE",
        "vulkan_enumeration_was_successful": observed["enumeration_completed_successfully"],
        "vulkan_enumeration_error_code": observed["vkEnumeratePhysicalDevices"] if not observed["enumeration_completed_successfully"] else None,
        "are_vkphysicaldevice_exposed": False,
        "are_vulkan_graphics_functional": False,
        "are_weighted_graphics_execution": False,
        "unity_runtime_verified": False,
    }
    rec["receipt_sha256"] = hashlib.sha256(
        json.dumps(rec, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return rec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rec = verify_loader(args.library, args.manifest, args.expected_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rec, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("ARE_REAL_KHRONOS_LOADER_ZERO_DEVICE_PASS " + rec["receipt_sha256"])


if __name__ == "__main__":
    main()
