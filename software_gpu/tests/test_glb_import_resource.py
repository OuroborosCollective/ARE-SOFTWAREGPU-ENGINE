"""Issue #293: genuine bounded GLB decode, memory and framebuffer regression."""
import gc
import hashlib
from pathlib import Path
import struct
import tempfile
import tracemalloc
import unittest

import numpy as np

from tools.glb_container_preflight import inspect_glb
from software_gpu.research.model_probe import accessor, load_asset, read_glb
from software_gpu.tests.fixtures.glb_resource_fixture import make_resource_glb
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex


class TestGLBImportResources(unittest.TestCase):
    def test_preflight_does_not_copy_eight_mib_bin_buffer(self):
        # RED on the historical implementation: data[pos:pos + size]
        # allocates a second full BIN copy just to check its declared length.
        raw = make_resource_glb(1, bin_bytes=8 << 20)
        gc.collect()
        tracemalloc.start()
        try:
            info = inspect_glb(raw)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(info["meshes"], 1)
        self.assertLess(peak, 4 << 20, "GLB_PREFLIGHT_DUPLICATED_BIN_BYTES")

    def test_real_glb_bytes_are_sha_pinned_and_native_subset_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for count, size in ((1, 256), (100, 4096), (1300, 16384), (3500, 65536)):
                with self.subTest(meshes=count):
                    raw = make_resource_glb(count, bin_bytes=size)
                    path = root / f"actual-{count}.glb"
                    path.write_bytes(raw)
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    self.assertEqual(inspect_glb(path.read_bytes())["meshes"], count)
                    doc, binary = read_glb(path, digest, path.stat().st_size)
                    self.assertEqual(len(doc["meshes"]), count)
                    self.assertEqual(len(binary), size)
                    np.testing.assert_array_equal(accessor(doc, binary, 1).reshape(-1), [0, 1, 2])
                    if count == 1:
                        asset = load_asset(path, {"sha256": digest, "bytes": len(raw)})
                        self.assertEqual(asset["metadata"]["triangles"], 1)
                    else:
                        with self.assertRaisesRegex(ValueError, "MODEL_MESH_SUBSET"):
                            load_asset(path, {"sha256": digest, "bytes": len(raw)})

    def test_overflow_bogus_stride_alignment_count_corrupt_accessor_and_reimport(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "actual.glb"
            raw = make_resource_glb(1)
            path.write_bytes(raw)
            entry = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            doc, binary = read_glb(path, entry["sha256"], entry["bytes"])
            for key, value in (("count", (1 << 63)), ("count", 0), ("bufferView", 10000)):
                corrupted = {**doc, "accessors": [dict(a) for a in doc["accessors"]]}
                corrupted["accessors"][0][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    accessor(corrupted, binary, 0)
                self.assertEqual(load_asset(path, entry)["metadata"]["triangles"], 1)
            for key, value in (("byteStride", 257), ("byteOffset", 1), ("byteLength", 1)):
                corrupted = {**doc, "bufferViews": [dict(v) for v in doc["bufferViews"]]}
                corrupted["bufferViews"][0][key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    accessor(corrupted, binary, 0)
            self.assertEqual(load_asset(path, entry)["metadata"]["triangles"], 1)
            bad = bytearray(raw)
            struct.pack_into("<I", bad, 8, len(raw) - 4)
            with self.assertRaises(ValueError):
                inspect_glb(bytes(bad))
            self.assertEqual(inspect_glb(raw)["meshes"], 1)

    def test_hundred_large_to_small_decode_release_cycles_do_not_retain_buffers(self):
        large, small = make_resource_glb(1300), make_resource_glb(1)
        with tempfile.TemporaryDirectory() as folder:
            bigger, little = Path(folder) / "large.glb", Path(folder) / "small.glb"
            bigger.write_bytes(large)
            little.write_bytes(small)
            large_entry = {"sha256": hashlib.sha256(large).hexdigest(), "bytes": len(large)}
            small_entry = {"sha256": hashlib.sha256(small).hexdigest(), "bytes": len(small)}
            gc.collect()
            tracemalloc.start()
            try:
                base, _ = tracemalloc.get_traced_memory()
                for _ in range(100):
                    doc, binary = read_glb(bigger, large_entry["sha256"], large_entry["bytes"])
                    self.assertEqual(len(doc["meshes"]), 1300)
                    del doc, binary
                    with self.assertRaisesRegex(ValueError, "MODEL_MESH_SUBSET"):
                        load_asset(bigger, large_entry)
                    self.assertEqual(load_asset(little, small_entry)["metadata"]["triangles"], 1)
                gc.collect()
                after, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertLess(after - base, 3 << 20)
            self.assertLess(peak, 32 << 20)

    def test_real_first_and_followup_cpu_draw_keep_rgba8_and_float32_depth(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "one.glb"
            raw = make_resource_glb(1)
            path.write_bytes(raw)
            asset = load_asset(path, {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
            mesh = [Vertex(np.asarray([*p, 1.], dtype=np.float32),
                           color=np.asarray([.8, .4, .2], dtype=np.float32))
                    for p in asset["positions"]]
            faces = [tuple(int(i) for i in f) for f in asset["faces"]]
            digests = []
            for _ in range(2):
                fb = Framebuffer(64, 64)
                fb.clear(16, 25, 38, 255, depth=1.0)
                renderer = SoftwareRasterizer(fb, backend="tiles", num_threads=1)
                try:
                    renderer.draw_mesh(mesh, faces, VertexColorShader())
                    self.assertEqual(fb.depth_buffer.dtype, np.dtype("<f4"))
                    self.assertEqual(fb.color_buffer.dtype, np.uint8)
                    self.assertGreater(int(np.count_nonzero(fb.depth_buffer < 1.)), 0)
                    digests.append((hashlib.sha256(fb.color_buffer.tobytes()).hexdigest(),
                                    hashlib.sha256(fb.depth_buffer.tobytes()).hexdigest()))
                finally:
                    renderer.executor.shutdown(wait=True)
            self.assertEqual(digests[0], digests[1])


if __name__ == "__main__":
    unittest.main()
