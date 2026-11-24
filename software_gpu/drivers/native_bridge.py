"""P0 ARE driver adaptation: real native CPU draws, NOT a Vulkan ICD.

This intentionally never registers a Vulkan driver, presents swapchains,
parses SPIR-V or reports a VkPhysicalDevice. The native bridge is an exact
capability-checked, synchronous C ABI adapter onto are::raster::draw.
"""
from contextlib import ExitStack
import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from threading import RLock
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


_MAX_DRIVER_BYTES = 64 * 1024 * 1024
_LOAD_LOCK = RLock()
# dlopen can reuse a loaded library by name. Keep its procfd name reserved for
# the life of the native image; ctypes does not unload images on object cleanup.
_LINUX_IMAGES = {}
_WINDOWS_DIGESTS = {}


def _verified_bytes(path, expected_sha256):
    # A nonblocking open avoids waiting on a FIFO before we can check its type.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) |
                 getattr(os, "O_BINARY", 0))
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_DRIVER_BYTES:
            raise ValueError("ARE_DRIVER_BINARY_SIZE_OR_TYPE")
        snapshot = source.read(_MAX_DRIVER_BYTES + 1)
    if not 0 < len(snapshot) <= _MAX_DRIVER_BYTES:
        raise ValueError("ARE_DRIVER_BINARY_SIZE_OR_TYPE")
    if hashlib.sha256(snapshot).hexdigest() != expected_sha256:
        raise ValueError("ARE_DRIVER_BINARY_HASH")
    return snapshot


def _load_linux(snapshot, digest):
    import fcntl

    with _LOAD_LOCK:
        if digest in _LINUX_IMAGES:
            return _LINUX_IMAGES[digest][1]
        # Linux UAPI values; some CPython builds omit these constants.
        add_seals = getattr(fcntl, "F_ADD_SEALS", 1033)
        seals = (getattr(fcntl, "F_SEAL_SEAL", 0x1) |
                 getattr(fcntl, "F_SEAL_SHRINK", 0x2) |
                 getattr(fcntl, "F_SEAL_GROW", 0x4) |
                 getattr(fcntl, "F_SEAL_WRITE", 0x8))
        fd = os.memfd_create("are-driver", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        try:
            with os.fdopen(os.dup(fd), "wb") as copy:
                copy.write(snapshot)
            fcntl.fcntl(fd, add_seals, seals)
            # Verify the sealed image itself before giving its path to dlopen.
            with os.fdopen(os.dup(fd), "rb") as sealed:
                sealed.seek(0)
                if (os.fstat(fd).st_size != len(snapshot) or
                        hashlib.file_digest(sealed, "sha256").hexdigest() != digest):
                    raise ValueError("ARE_DRIVER_BINARY_HASH")
            lib = ctypes.CDLL(f"/proc/self/fd/{fd}")
        except BaseException:
            os.close(fd)
            raise
        _LINUX_IMAGES[digest] = (fd, lib)
        return lib


def _load_windows(path, digest):
    import _winapi
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    drive_type = kernel.GetDriveTypeW
    drive_type.argtypes = (wintypes.LPCWSTR,)
    drive_type.restype = wintypes.UINT
    # Keep Win32 loader name normalization and remote filesystems outside
    # the pinned-path contract. All repository Windows builds produce DLLs.
    if (len(path.drive) != 2 or path.drive[1] != ":" or
            drive_type(path.anchor) not in (3, 6) or  # DRIVE_FIXED, DRIVE_RAMDISK
            path.suffix.lower() != ".dll" or any(":" in p for p in path.parts[1:])):
        raise ValueError("ARE_DRIVER_BINARY_PATH")
    file_info = kernel.GetFileInformationByHandleEx
    file_info.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    file_info.restype = wintypes.BOOL
    get_module = kernel.GetModuleHandleW
    get_module.argtypes = (wintypes.LPCWSTR,)
    get_module.restype = wintypes.HMODULE
    generic_read, share_read, open_existing = 0x80000000, 1, 3
    backup_semantics, open_reparse_point = 0x02000000, 0x00200000
    file_attribute_tag_info = 9
    # Pin each component from the drive root down. Reject reparse points so
    # later lookups cannot escape the pinned chain. FILE_SHARE_READ denies
    # write and delete access, including existing writable mappings. A rename
    # also requires write access to the destination directory, including when
    # replacing a target via POSIX rename semantics.
    with _LOAD_LOCK, ExitStack() as pins:
        for part in (*reversed(path.parents), path):
            handle = _winapi.CreateFile(str(part), generic_read, share_read, 0,
                                        open_existing, backup_semantics | open_reparse_point, 0)
            pins.callback(_winapi.CloseHandle, handle)
            tag_info = (wintypes.DWORD * 2)()
            if not file_info(handle, file_attribute_tag_info, tag_info, ctypes.sizeof(tag_info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if tag_info[0] & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError("ARE_DRIVER_BINARY_REPARSE_POINT")

        _verified_bytes(path, digest)
        loaded = get_module(str(path))
        if loaded and _WINDOWS_DIGESTS.get(loaded) != digest:
            raise ValueError("ARE_DRIVER_BINARY_ALREADY_LOADED")
        # These builds use static C++ runtime linking. Do not search the
        # artifact's directory for dependencies of the verified image.
        load_library_search_default_dirs = 0x1000
        lib = ctypes.CDLL(str(path), winmode=load_library_search_default_dirs)
        _WINDOWS_DIGESTS[lib._handle] = digest
        return lib


class AREDriverBridge:
    """Trusted, digest-pinned native CPU entry point; callers own their buffers."""
    def __init__(self, binary, expected_sha256):
        self.binary_path = Path(binary).resolve()
        if sys.platform == "linux":
            snapshot = _verified_bytes(self.binary_path, expected_sha256)
            self._lib = _load_linux(snapshot, expected_sha256)
        elif sys.platform == "win32":
            self._lib = _load_windows(self.binary_path, expected_sha256)
        else:
            raise OSError("ARE_DRIVER_SECURE_LOAD_UNSUPPORTED")
        self.binary_sha256 = expected_sha256
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
