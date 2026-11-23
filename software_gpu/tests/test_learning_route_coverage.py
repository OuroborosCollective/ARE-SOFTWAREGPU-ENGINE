"""Proof of actual local learning coverage for SoftwareGPU output routes.

A persisted paired draw controls the real pixel/depth buffers. Deterministic
weight edits below are behavioral controls only, NOT production timing evidence.
"""
import ast
from contextlib import closing
import hashlib
import importlib.util
from fractions import Fraction
import subprocess
import inspect
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.native_raster import NativeRasterKernel, build_raster_kernel
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.learning import LocalLearner

PUBLIC_RASTER_BACKENDS = ("tiles", "tiles-jit", "tiles-plan", "tiles-deferred", "bands", "native-cpp")

# Scope inventory: "active" is not claimed for native probes, external
# Blender, or byte-only serializers. A new route requires explicit review.
ROUTE_INVENTORY = {
    "software_gpu/graphics/rasterizer.py": {
        "SoftwareRasterizer.draw_mesh": "weights-active-raster",
    },
    "software_gpu/integrations/render_video.py": {
        "encode_frames": "weights-active-video",
    },
    "software_gpu/graphics/framebuffer.py": {
        "Framebuffer.save_ppm": "inherits-weighted-byte-export",
        "Framebuffer.save_bmp": "inherits-weighted-byte-export",
        "Framebuffer.to_ppm_bytes": "weights-active-byte-export",
        "Framebuffer.to_bmp_bytes": "weights-active-byte-export",
    },
    "software_gpu/research/model_probe.py": {
        "run_model": "weights-active-native-auto",
        "write_scene": "unweighted-input-serializer",
    },
    "tools/visual_asset_lab_native.py": {
        "render_native_asset_lab": "delegates-verified-native-auto",
    },
    "software_gpu/integrations/blender/blender_render_engine.py": {
        "StandaloneBlenderBridge.render_scene": "delegates-weighted-raster",
    },
    "software_gpu/integrations/aurion/offline_render_worker.py": {
        "run_job": "delegates-weighted-aurion-child",
        "compare_backends": "delegates-weighted-raster",
    },
    "tools/ktx2_texture_admission.py": {
        "convert_ktx2_glb": "weights-active-ktx",
    },
    "software_gpu/drivers/command_submission.py": {
        "submit_native_draws": "weights-active-native-command",
        "record_native_draws": "unweighted-immutable-input-recorder",
    },
    "software_gpu/drivers/native_bridge.py": {
        "AREDriverBridge.draw_packed": "unweighted-lowlevel-native-abi",
    },
    "software_gpu/drivers/spirv_execution_smoke.py": {
        "execute": "delegates-weighted-raster",
    },
    "software_gpu/drivers/spirv_opcode_executor.py": {
        "RestrictedSpirvColorShader.vertex_shader": "unweighted-shader-callback",
        "RestrictedSpirvColorShader.fragment_shader": "unweighted-shader-callback",
    },
    "software_gpu/drivers/vulkan_reference.py": {
        "run_reference_probe": "unweighted-external-mesa-preflight",
    },
}


def route_method_source(file_path, qualname):
    root = ast.parse(file_path.read_text(encoding="utf-8"))
    target = root.body
    for index, part in enumerate(qualname.split('.')):
        matches = [n for n in target if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                   and n.name == part]
        if len(matches) != 1:
            raise AssertionError("Missing/duplicate route: " + str(file_path) + "::" + qualname)
        node = matches[0]
        target = getattr(node, "body", [])
    return ast.get_source_segment(file_path.read_text(encoding="utf-8"), node)



def declared_backends():
    source = inspect.getsource(SoftwareRasterizer.__init__)
    root = ast.parse("def " + source.split("def ", 1)[1])
    # Guard exact source-dispatch inventory, rather than a manually chosen subset.
    tuples = [n for n in ast.walk(root) if isinstance(n, ast.Tuple) and
              all(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in n.elts)]
    candidates = [tuple(x.value for x in n.elts) for n in tuples]
    return next(x for x in candidates if "native-cpp" in x and "tiles" in x)


class LearningRoutingCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="are-learn-routes-")
        cls.binary, cls.build_receipt = build_raster_kernel(cls.temp.name)
        cls.kernel = NativeRasterKernel(cls.binary, cls.build_receipt["binary_sha256"])

    @classmethod
    def tearDownClass(cls):
        import sys
        if sys.platform == "win32":
            cls.temp._finalizer.detach()  # Native library DLL remains loaded
        else:
            cls.temp.cleanup()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="are-learn-case-")
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / "weights.sqlite3"
        self.vertices, self.faces = make_fixture(4, .55)

    def render(self, backend, *, learning=True):
        with patch.dict(os.environ, {"ARE_LEARNING_DB": str(self.db) if learning else "off"}):
            fb = Framebuffer(43, 39)
            fb.clear(14, 33, 61, 200, .9)
            fb.depth_buffer[::3, ::3] = 0
            r = SoftwareRasterizer(fb, backend=backend, tile_size=8, num_threads=1,
                                   native_kernel=self.kernel if backend == "native-cpp" else None)
            try:
                r.draw_mesh(self.vertices, self.faces, VertexColorShader())
                return (fb.color_buffer.tobytes(), fb.depth_buffer.tobytes(),
                        r.last_learning_receipt)
            finally:
                r.executor.shutdown()

    def test_every_registered_raster_backend_reaches_sqlite_with_real_color_depth(self):
        self.assertEqual(set(declared_backends()), set(PUBLIC_RASTER_BACKENDS),
                         "New render backend requires explicit learning coverage")
        for backend in PUBLIC_RASTER_BACKENDS:
            with self.subTest(backend=backend):
                if backend == "tiles-jit" and importlib.util.find_spec("numba") is None:
                    # The default wheel intentionally omits optional Numba.
                    # This path must fail closed. The dedicated native CI job
                    # installs [jit] and exercises real learned raster output.
                    with self.assertRaisesRegex(RuntimeError, "tiles-jit requires optional Numba"):
                        self.render(backend, learning=False)
                    continue
                baseline = self.render(backend, learning=False)
                self.assertIsNone(baseline[2])
                learned = self.render(backend)
                self.assertEqual(learned[:2], baseline[:2])
                receipt = learned[2]
                self.assertIsNotNone(receipt, "missing runtime learning receipt: " + backend)
                self.assertEqual(receipt["scope"]["backend"], backend) if isinstance(receipt["scope"], dict) else self.assertEqual(json.loads(receipt["scope"])["backend"], backend)
                self.assertEqual(receipt["served"], "reference")
                profile = [p for p in LocalLearner(self.db).status() if p["scope"].get("backend") == backend]
                self.assertEqual(len(profile), 1, "route missing persistent weight profile: " + backend)
                self.assertEqual(profile[0]["runs"], 1)
                self.assertGreater(profile[0]["reference_ns"], 0)
                self.assertEqual(LocalLearner(self.db).samples()[0]["scope"], receipt["scope"])

    def test_actual_trained_weights_control_safe_tile_variant_not_only_logging(self):
        baseline = self.render("tiles", learning=False)
        first = self.render("tiles")
        self.assertEqual(first[:2], baseline[:2])
        self.assertEqual(first[2]["outcome"], "matched")
        key = first[2]["scope"]
        # Controlled SQLite weight snapshot tests *routing*, not performance.
        # Real A/B work and buffer fingerprints were validated above.
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("UPDATE models SET runs=5,pairs=4,reference_ns=10000,"
                        "candidate_ns=1000,log_gain=?,recent_wins=15,blocked=0 WHERE scope=?",
                        (math.log(10), key))
        candidate = self.render("tiles")
        self.assertEqual(candidate[2]["served"], "candidate")
        self.assertEqual(candidate[2]["outcome"], "single")
        self.assertEqual(candidate[:2], baseline[:2])
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("UPDATE models SET blocked=1 WHERE scope=?", (key,))
        reference = self.render("tiles")
        self.assertEqual(reference[2]["served"], "reference")
        self.assertEqual(reference[:2], baseline[:2])
        self.assertGreaterEqual(len(LocalLearner(self.db).samples()), 3)

    def test_all_explicit_render_and_output_surfaces_have_truthful_weight_classification(self):
        project = Path(__file__).resolve().parents[2]
        declared = {}
        for file, methods in ROUTE_INVENTORY.items():
            for method, status in methods.items():
                src = route_method_source(project / file, method)
                declared[file + "::" + method] = status
                if status == "weights-active-raster":
                    self.assertIn("self.local_learner", src)
                elif status == "weights-active-video":
                    self.assertIn("configured_learner", src)
                    self.assertIn("learner.execute", src)
                elif status == "weights-active-byte-export":
                    self.assertIn("measured_bytes", src)
                elif status == "weights-active-native-auto":
                    self.assertIn("learner.execute", src)
                    self.assertIn("workers == 'auto'", src)
                elif status == "weights-active-ktx":
                    self.assertIn("learner.execute", src)
                elif status == "weights-active-native-command":
                    self.assertIn("configured_learner", src)
                    self.assertIn("learner.execute", src)
                    self.assertIn("fingerprint", src)
                    self.assertIn("np.copyto", src)
                    self.assertIn("bridge.draw_packed", src)
                elif status == "delegates-verified-native-auto":
                    self.assertIn("workers='auto'", src)
                    self.assertIn("NATIVE_WORKER_BUFFER_MISMATCH", src)
                elif status == "delegates-weighted-raster":
                    self.assertTrue(any(token in src for token in (
                        "SoftwareRasterizer", "_render_mesh")))
                elif status == "delegates-weighted-aurion-child":
                    self.assertIn("_CHILD_BOOTSTRAP", src)
                elif status == "inherits-weighted-byte-export":
                    self.assertTrue(any(token in src for token in (
                        "to_bmp_bytes", "to_ppm_bytes")))
                elif status.startswith("unweighted"):
                    self.assertNotIn("learner.execute", src)
        self.assertGreaterEqual(len(declared), 13)
        self.assertEqual(sum(v.startswith("weights-active") for v in declared.values()), 7)
        # Active means the route *offers* measured alternatives when the
        # learner is enabled. Pinned worker paths and pure input serializers
        # are deliberately not claimed as adaptively selectable.

    def test_mp4_and_ffv1_export_use_saved_weights_on_actual_ffmpeg(self):
        from software_gpu.integrations.render_video import encode_frames, media_binaries
        try:
            ffmpeg, ffprobe = media_binaries()
        except FileNotFoundError as exc:
            self.skipTest("Actual FFmpeg not installed: " + str(exc))
        root = Path(self.folder.name)
        frames = []
        for i in range(3):
            img = root / f"frame-{i}.ppm"
            img.write_bytes(b"P6\n16 16\n255\n" + bytes([40+i, 80, 130]) * (16*16))
            frames.append(img)
        for suffix, codec in ((".mkv", "ffv1"), (".mp4", "h264")):
            with self.subTest(codec=codec), patch.dict(os.environ, {"ARE_LEARNING_DB": str(self.db)}):
                out = root / ("result-" + codec + suffix)
                receipt = encode_frames(out, frames, Fraction(12), ffmpeg, ffprobe)
                self.assertTrue(out.is_file())
                self.assertEqual(receipt["codec_name"], codec)
                self.assertEqual(receipt["learning"]["scope"], LocalLearner(self.db).samples()[0]["scope"])
                self.assertEqual(json.loads(receipt["learning"]["scope"])["stage"], "ffmpeg")
                self.assertEqual(receipt["learning"]["outcome"], "matched")
                self.assertGreater(len(out.read_bytes()), 0)
                profiles = [p for p in LocalLearner(self.db).status()
                            if p['scope']['stage'] == 'ffmpeg'
                            and p['scope']['codec'] == codec]
                self.assertEqual(len(profiles), 1)
                self.assertGreater(profiles[0]['runs'], 0)

    def test_export_entrypoints_preserve_upstream_weighted_pixels(self):
        color, depth, receipt = self.render("tiles")
        self.assertEqual(receipt["scope"], LocalLearner(self.db).samples()[0]["scope"])
        with patch.dict(os.environ, {"ARE_LEARNING_DB": str(self.db)}):
            fb = Framebuffer(43,39)
            fb.color_buffer[:] = __import__('numpy').frombuffer(color, dtype='u1').reshape(39,43,4)
            fb.depth_buffer[:] = __import__('numpy').frombuffer(depth, dtype='<f4').reshape(39,43)
            png = Path(self.folder.name) / 'render.ppm'
            bmp = Path(self.folder.name) / 'render.bmp'
            fb.save_ppm(png)
            fb.save_bmp(bmp)
            self.assertEqual(bmp.read_bytes(), fb.to_bmp_bytes())
            self.assertEqual(png.read_bytes().split(b'\n', 3)[-1],
                             fb.color_buffer[..., :3].tobytes())
            self.assertEqual(LocalLearner(self.db).status()[0]["scope"]["stage"], "raster")
            # The current image-byte writers do not have independent candidate
            # implementations. Their source raster is still weight-bound.
            # Do not misreport byte serializers as independently learned.


if __name__ == "__main__":
    unittest.main()
