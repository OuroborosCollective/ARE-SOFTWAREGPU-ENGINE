"""P0 ARE driver adaptation: real native CPU draws, NOT a Vulkan ICD.

This intentionally never registers a Vulkan driver, presents swapchains,
parses SPIR-V or reports a VkPhysicalDevice. The native bridge is an exact
capability-checked, synchronous C ABI adapter onto are::raster::draw.
"""
import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from software_gpu.graphics.native_raster import NATIVE
from software_gpu.research.native_symbolic import FLAGS, compiler


class DriverCapabilitiesV1(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("device_kind", ctypes.c_uint32),
        ("profile_bits", ctypes.c_uint32),
        ("supports_spirv", ctypes.c_uint32),
        ("supports_vulkan_icd", ctypes.c_uint32),
        ("supports_wsi", ctypes.c_uint32),
        ("max_width", ctypes.c_uint32),
        ("max_height", ctypes.c_uint32),
        ("max_pixels", ctypes.c_uint32),
        ("max_triangles", ctypes.c_uint32),
    ]


class DriverDrawV1(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("profile", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("packed", ctypes.c_void_p),
        ("cells", ctypes.c_size_t),
        ("count", ctypes.c_size_t),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("rgba", ctypes.c_void_p),
        ("rgba_bytes", ctypes.c_size_t),
        ("depth", ctypes.c_void_p),
        ("depth_cells", ctypes.c_size_t),
        ("counts", ctypes.c_void_p),
        ("count_cells", ctypes.c_size_t),
    ]


def build_driver_bridge(directory):
    """Explicit source-checkout C++17 build, no system installation or loader registration."""
    target = Path(directory).resolve()
    sources = {name: (NATIVE / name).read_bytes() for name in (
        "raster/core.hpp",
        "raster/driver_adapter.hpp",
        "raster/driver_adapter.cpp",
        "symbolic/core.hpp",
    )}
    for name, data in sources.items():
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    binary = target / ("are_driver.dll" if sys.platform == "win32" else "libare_driver.so")
    shared = ["-shared", "-static"] if sys.platform == "win32" else ["-shared", "-fPIC"]
    cxx = compiler()
    command = [cxx, *FLAGS, *shared, str(target / "raster/driver_adapter.cpp"), "-o", str(binary)]
    started = time.perf_counter_ns()
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("ARE_DRIVER_BUILD_FAILED:" + result.stderr[-6000:])
    receipt = {
        "protocol": "are.driver-adapter-build.v1",
        "compiler": cxx,
        "compiler_version": subprocess.check_output([cxx, "--version"], text=True).splitlines()[0],
        "flags": [*FLAGS, *shared],
        "compile_ms": (time.perf_counter_ns() - started) / 1e6,
        "source_sha256": {name: hashlib.sha256(data).hexdigest()
                          for name, data in sorted(sources.items())},
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "compiler_diagnostics": result.stderr,
        "vulkan_icd": False,
        "loader_enumeration_verified": False,
    }
    (target / "build.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n",
                                       encoding="utf-8")
    return binary, receipt


class AREDriverBridge:
    """Trusted, digest-pinned native CPU entry point; callers own their buffers."""
    def __init__(self, binary, expected_sha256):
        self.binary_path = Path(binary).resolve()
        self.binary_sha256 = hashlib.sha256(self.binary_path.read_bytes()).hexdigest()
        if self.binary_sha256 != expected_sha256:
            raise ValueError("ARE_DRIVER_BINARY_HASH")
        self._lib = ctypes.CDLL(str(self.binary_path))
        self._lib.are_driver_abi.argtypes = []
        self._lib.are_driver_abi.restype = ctypes.c_uint32
        if self._lib.are_driver_abi() != 1:
            raise ValueError("ARE_DRIVER_ABI")
        self._lib.are_driver_capabilities_v1.argtypes = [
            ctypes.POINTER(DriverCapabilitiesV1), ctypes.c_size_t
        ]
        self._lib.are_driver_capabilities_v1.restype = ctypes.c_int
        caps = DriverCapabilitiesV1()
        status = self._lib.are_driver_capabilities_v1(
            ctypes.byref(caps), ctypes.sizeof(caps))
        if status or (caps.struct_size != ctypes.sizeof(caps) or
                      caps.abi_version != 1 or caps.device_kind != 1 or
                      caps.profile_bits != 1 or
                      caps.supports_spirv or caps.supports_vulkan_icd or caps.supports_wsi):
            raise ValueError("ARE_DRIVER_CAPABILITY_CONTRACT")
        self.capabilities = caps
        self._draw = self._lib.are_driver_draw_v1
        self._draw.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        self._draw.restype = ctypes.c_int

    def _make_draw(self, framebuffer, packed):
        """Validated zero-copy descriptor for a trusted synchronous in-process call."""
        width, height = framebuffer.width, framebuffer.height
        caps = self.capabilities
        if (type(width) is not int or type(height) is not int or
                not 1 <= width <= caps.max_width or
                not 1 <= height <= caps.max_height or
                width * height > caps.max_pixels):
            raise ValueError("ARE_DRIVER_FRAME_BUDGET")
        if (type(packed) is not np.ndarray or packed.dtype != np.dtype("float64") or
                packed.ndim != 2 or packed.shape[1] != 23 or
                packed.shape[0] > caps.max_triangles or
                not packed.flags.c_contiguous or not packed.flags.aligned):
            raise ValueError("ARE_DRIVER_PACKED_BUFFER")

        rgba = framebuffer.color_buffer
        depth = framebuffer.depth_buffer
        for array, dtype, shape in (
            (rgba, np.dtype("uint8"), (height, width, 4)),
            (depth, np.dtype("float32"), (height, width)),
        ):
            if (type(array) is not np.ndarray or array.dtype != dtype or
                    array.shape != shape or not array.flags.c_contiguous or
                    not array.flags.aligned or not array.flags.writeable):
                raise ValueError("ARE_DRIVER_FRAME_BUFFER")
        if (np.shares_memory(rgba, depth) or
                np.shares_memory(packed, rgba) or np.shares_memory(packed, depth)):
            raise ValueError("ARE_DRIVER_BUFFER_ALIAS")
        counts = np.zeros(3, dtype=np.uint64)
        draw = DriverDrawV1()
        draw.struct_size = ctypes.sizeof(draw)
        draw.profile = 1
        draw.packed = packed.ctypes.data
        draw.cells = packed.size
        draw.count = packed.shape[0]
        draw.width = width
        draw.height = height
        draw.rgba = rgba.ctypes.data
        draw.rgba_bytes = rgba.nbytes
        draw.depth = depth.ctypes.data
        draw.depth_cells = depth.size
        draw.counts = counts.ctypes.data
        draw.count_cells = counts.size
        return draw, counts

    def draw_packed(self, framebuffer, packed):
        """Execute the real CPU raster path; returns only observed color/depth evidence."""
        draw, counts = self._make_draw(framebuffer, packed)
        # The local references retain NumPy buffers throughout the C++ call.
        status = self._draw(ctypes.byref(draw), ctypes.sizeof(draw))
        if status:
            raise ValueError("ARE_DRIVER_DRAW_REJECTED:" + str(status))
        return {
            "protocol": "are.driver-adapter-render.v1",
            "binary_sha256": self.binary_sha256,
            "device_kind": "cpu-software",
            "profile": "packed-vertex-color",
            "supports_vulkan_icd": False,
            "candidate_samples": int(counts[0]),
            "covered_samples": int(counts[1]),
            "shaded_samples": int(counts[2]),
            "rgba_sha256": hashlib.sha256(framebuffer.color_buffer.tobytes()).hexdigest(),
            "depth_sha256": hashlib.sha256(framebuffer.depth_buffer.tobytes()).hexdigest(),
        }
