"""Real C++17 driver-adaptation tests; no Vulkan-ICD or Unity claims."""
import copy
import ctypes
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.geometry import prepare_triangles
from software_gpu.graphics.native_raster import (
    NativeRasterKernel, build_raster_kernel, pack_triangles,
)
from software_gpu.drivers.native_bridge import (
    AREDriverBridge, DriverDrawV1, build_driver_bridge,
)


class TestDriverBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="are-driver-test-")
        root = Path(cls.temp.name)
        binary, build_receipt = build_driver_bridge(root / "driver")
        cls.bridge = AREDriverBridge(binary, build_receipt["binary_sha256"])
        raster_binary, raster_receipt = build_raster_kernel(root / "raster")
        cls.raster = NativeRasterKernel(raster_binary, raster_receipt["binary_sha256"])

    @classmethod
    def tearDownClass(cls):
        if __import__("sys").platform == "win32":
            # Keep DLLs mapped on Windows until interpreter exit.
            cls.temp._finalizer.detach()
        else:
            cls.temp.cleanup()

    def make_triangles(self):
        mesh, faces = make_fixture(4, 0.8)
        prepared = prepare_triangles(mesh, faces, VertexColorShader(), 32, 24)
        self.assertTrue(prepared)
        return prepared

    def test_real_native_frame_color_depth_and_replay(self):
        prepared = self.make_triangles()
        actual, reference, replay = (Framebuffer(32, 24) for _ in range(3))
        for fb in (actual, reference, replay):
            fb.clear()
        receipt = self.bridge.draw_packed(actual, pack_triangles(prepared))
        reference_receipt = self.raster.draw(reference, prepared, VertexColorShader())
        replay_receipt = self.bridge.draw_packed(replay, pack_triangles(prepared))
        self.assertEqual(actual.color_buffer.tobytes(), reference.color_buffer.tobytes())
        self.assertEqual(actual.depth_buffer.tobytes(), reference.depth_buffer.tobytes())
        self.assertEqual(actual.color_buffer.tobytes(), replay.color_buffer.tobytes())
        self.assertEqual(actual.depth_buffer.tobytes(), replay.depth_buffer.tobytes())
        self.assertEqual(receipt["rgba_sha256"], replay_receipt["rgba_sha256"])
        self.assertEqual(receipt["depth_sha256"], replay_receipt["depth_sha256"])
        self.assertEqual(receipt["shaded_samples"], reference_receipt["shaded_samples"])
        self.assertGreater(receipt["shaded_samples"], 0)
        self.assertEqual(receipt["protocol"], "are.driver-adapter-render.v1")

    def test_capabilities_are_truthful_not_an_icd(self):
        caps = self.bridge.capabilities
        self.assertEqual(caps.abi_version, 1)
        self.assertEqual(caps.device_kind, 1)  # Software CPU
        self.assertEqual(caps.profile_bits, 1)  # Packed vertex-color triangle only
        self.assertEqual((caps.supports_spirv, caps.supports_vulkan_icd, caps.supports_wsi),
                         (0, 0, 0))
        self.assertEqual((caps.max_width, caps.max_height, caps.max_pixels, caps.max_triangles),
                         (4096, 4096, 4194304, 200000))
        with self.assertRaises(AttributeError):
            getattr(self.bridge._lib, "vk_icdGetInstanceProcAddr")

    def test_rejects_unsupported_spirv_and_wsi_without_mutation(self):
        prepared = self.make_triangles()
        packed = pack_triangles(prepared)
        fb = Framebuffer(32, 24)
        fb.clear()
        baseline = (fb.color_buffer.tobytes(), fb.depth_buffer.tobytes())
        draw, counts = self.bridge._make_draw(fb, packed)
        for field, value in (("profile", 2), ("flags", 1), ("reserved", 1)):
            changed = DriverDrawV1.from_buffer_copy(draw)
            setattr(changed, field, value)
            status = self.bridge._draw(ctypes.byref(changed), ctypes.sizeof(changed))
            self.assertEqual(status, 7, field)  # Unsupported capability
            self.assertEqual((fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()), baseline)
        bad_size = DriverDrawV1.from_buffer_copy(draw)
        bad_size.struct_size -= 1
        self.assertEqual(self.bridge._draw(ctypes.byref(bad_size), ctypes.sizeof(bad_size)), 6)
        self.assertEqual((fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()), baseline)
        self.assertTrue(np.all(counts == 0))

    def test_late_bad_triangle_is_atomic_and_buffers_do_not_overlap(self):
        prepared = self.make_triangles()
        packed = pack_triangles(prepared)
        broken = np.concatenate([packed, packed[:1]], axis=0)
        broken[-1, 0] = np.nan
        fb = Framebuffer(32, 24)
        fb.clear()
        before = (fb.color_buffer.tobytes(), fb.depth_buffer.tobytes())
        draw, counts = self.bridge._make_draw(fb, broken)
        self.assertEqual(self.bridge._draw(ctypes.byref(draw), ctypes.sizeof(draw)), 4)
        self.assertEqual((fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()), before)
        self.assertTrue(np.all(counts == 0))
        overlap = DriverDrawV1.from_buffer_copy(draw)
        overlap.depth = overlap.rgba
        self.assertEqual(self.bridge._draw(ctypes.byref(overlap), ctypes.sizeof(overlap)), 8)
        self.assertEqual((fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()), before)

    @unittest.skipUnless(sys.platform == "linux", "Linux sealed image")
    def test_native_image_is_sealed_and_matches_approved_binary(self):
        import fcntl

        with open(self.bridge._lib._name, "rb") as image:
            self.assertFalse(os.path.samestat(os.fstat(image.fileno()),
                                              self.bridge.binary_path.stat()))
            seals = fcntl.fcntl(image, getattr(fcntl, "F_GET_SEALS", 1034))
            required = 0xF  # Linux UAPI: seal, shrink, grow, write.
            self.assertEqual(seals & required, required)
            self.assertEqual(hashlib.file_digest(image, "sha256").hexdigest(),
                             self.bridge.binary_sha256)

    @unittest.skipUnless(sys.platform == "win32", "Windows DLL path pins")
    def test_driver_directory_is_pinned_during_native_load(self):
        import _winapi

        load = ctypes.CDLL
        binary = self.bridge.binary_path

        def check_pins(name, **kwargs):
            for part, flags in ((binary, 0), (binary.parent, 0x02000000)):
                with self.assertRaises(OSError) as denied:
                    _winapi.CreateFile(str(part), 0x40000000, 7, 0, 3, flags, 0)
                self.assertEqual(denied.exception.winerror, 32)  # Sharing violation.
            return load(name, **kwargs)

        with patch("ctypes.CDLL", side_effect=check_pins) as patched:
            AREDriverBridge(binary, self.bridge.binary_sha256)
            patched.assert_called_once()

    def test_oversized_driver_is_rejected_before_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "oversized.dll"
            with binary.open("wb") as stream:
                stream.truncate(64 * 1024 * 1024 + 1)
            with patch("ctypes.CDLL") as load:
                with self.assertRaisesRegex(ValueError, "BINARY_SIZE_OR_TYPE"):
                    AREDriverBridge(binary, "0" * 64)
                load.assert_not_called()

    def test_binary_hash_and_packed_buffer_validation(self):
        with self.assertRaisesRegex(ValueError, "BINARY_HASH"):
            AREDriverBridge(self.bridge.binary_path, "0" * 64)
        fb = Framebuffer(4, 4)
        fb.clear()
        for bad in (
            np.zeros((1, 23), np.float32),
            np.zeros((1, 22), np.float64),
            np.zeros((2, 23), np.float64)[::-1],
        ):
            before = (fb.color_buffer.tobytes(), fb.depth_buffer.tobytes())
            with self.assertRaisesRegex(ValueError, "DRIVER_PACKED_BUFFER"):
                self.bridge.draw_packed(fb, bad)
            self.assertEqual((fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()), before)


if __name__ == "__main__":
    unittest.main()
