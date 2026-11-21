"""Real SQLite-weighted output, Blender and native model routing evidence.

Controlled SQLite values prove *selection*, not a real-world speedup.
"""
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.learning import LocalLearner


class OutputLearningIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="are-learn-outputs-")
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "learn.sqlite3"
        self.env = patch.dict(os.environ, {"ARE_LEARNING_DB": str(self.db)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.fb = Framebuffer(19, 13)  # Non-aligned BMP row stride.
        self.fb.clear(19, 83, 211, 173, .8)
        self.fb.color_buffer[2:8, 3:12] = [237, 4, 73, 255]
        self.fb.depth_buffer[2:8, 3:12] = np.float32(.21)

    def test_ppm_and_bmp_are_independently_weighted_and_byte_identical(self):
        color = self.fb.color_buffer.tobytes()
        depth = self.fb.depth_buffer.tobytes()
        with patch.dict(os.environ, {"ARE_LEARNING_DB": "off"}):
            reference_bmp = self.fb.to_bmp_bytes()
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "old.ppm"
                self.fb.save_ppm(p)
                reference_ppm = p.read_bytes()
        for _ in range(4):
            actual_bmp = self.fb.to_bmp_bytes()
            self.assertEqual(actual_bmp, reference_bmp)
            self.assertEqual(json.loads(self.fb.last_export_learning_receipt["scope"])["stage"],
                             "bmp-byte-export")
        bmp_profile = next(x for x in LocalLearner(self.db).status()
                           if x["scope"]["stage"] == "bmp-byte-export")
        self.assertEqual(bmp_profile["pairs"], 4)
        self.assertFalse(bmp_profile["blocked"])
        # Changing only the controlled learning state proves that the
        # *saved* weight is consulted. This is NOT benchmark evidence.
        bmp_scope = json.dumps(bmp_profile["scope"], sort_keys=True, separators=(",", ":"))
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("UPDATE models SET runs=5,pairs=4,reference_ns=10000,"
                        "candidate_ns=1000,log_gain=?,recent_wins=15,blocked=0 WHERE scope=?",
                        (math.log(10), bmp_scope))
        self.assertEqual(self.fb.to_bmp_bytes(), reference_bmp)
        self.assertEqual(self.fb.last_export_learning_receipt["served"], "candidate")
        for _ in range(4):
            self.assertEqual(self.fb.to_ppm_bytes(), reference_ppm)
        ppm_profile = next(x for x in LocalLearner(self.db).status()
                           if x["scope"]["stage"] == "ppm-byte-export")
        self.assertEqual(ppm_profile["pairs"], 4)
        ppm_scope = json.dumps(ppm_profile["scope"], sort_keys=True, separators=(",", ":"))
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("UPDATE models SET runs=5,pairs=4,reference_ns=10000,"
                        "candidate_ns=1000,log_gain=?,recent_wins=15,blocked=0 WHERE scope=?",
                        (math.log(10), ppm_scope))
        ppm = Path(self.temp.name) / "pixels.ppm"
        self.fb.save_ppm(ppm)
        self.assertEqual(ppm.read_bytes(), reference_ppm)
        self.assertEqual(self.fb.last_export_learning_receipt["served"], "candidate")
        self.assertEqual(json.loads(self.fb.last_export_learning_receipt["scope"])["stage"],
                         "ppm-byte-export")
        bmp = Path(self.temp.name) / "pixels.bmp"
        self.fb.save_bmp(bmp)
        self.assertEqual(bmp.read_bytes(), reference_bmp)
        self.assertEqual(self.fb.color_buffer.tobytes(), color)
        self.assertEqual(self.fb.depth_buffer.tobytes(), depth)
        self.assertEqual({r["scope"]["stage"] for r in LocalLearner(self.db).status()},
                         {"bmp-byte-export", "ppm-byte-export"})

    def test_blender_softwaregpu_bridge_propagates_real_raster_and_export_weights(self):
        from software_gpu.integrations.blender.blender_render_engine import StandaloneBlenderBridge
        from software_gpu.graphics.shader import Vertex
        vertices = [Vertex(np.array(p, dtype=np.float32),
                           normal=np.array([0., 0., 1.], dtype=np.float32))
                    for p in ((-.7, -.6, 0.), (.8, -.6, 0.), (0., .9, 0.))]
        bridge = StandaloneBlenderBridge(40, 32)
        output = Path(self.temp.name) / "bridge.bmp"
        fb = bridge.render_scene(vertices, [(0, 1, 2)],
                                 np.array([0., 0., 4.], dtype=np.float32),
                                 np.array([0., 0., 0.], dtype=np.float32),
                                 output_filepath=str(output))
        self.assertTrue(output.is_file())
        self.assertEqual(output.read_bytes(), fb.to_bmp_bytes())
        self.assertEqual(json.loads(bridge.last_learning_receipt["scope"])["stage"], "raster")
        self.assertEqual(json.loads(bridge.last_export_learning_receipt["scope"])["stage"],
                         "bmp-byte-export")
        self.assertEqual({r["scope"]["stage"] for r in LocalLearner(self.db).status()},
                         {"raster", "bmp-byte-export"})


class NativeModelAutoLearning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from software_gpu.research.model_probe import build_model_probe
        cls.temp = tempfile.TemporaryDirectory(prefix="are-native-auto-")
        cls.root = Path(cls.temp.name)
        cls.binary, cls.build = build_model_probe(cls.root / "native")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_native_auto_workers_choose_by_persisted_weights_after_real_parity(self):
        from software_gpu.research.model_probe import load_asset, write_scene, run_model
        from software_gpu.tests.fixtures.model_fixture import make_glb
        fixture = self.root / "autoweight-fixture.glb"
        metadata = make_glb(fixture, static=True)
        asset = load_asset(fixture, metadata)
        request = self.root / "autoweight-request.aremdl"
        write_scene(request, [dict(asset=asset, clip=None)], [0.0],
                    pixels=32, tile=16)
        with tempfile.TemporaryDirectory(prefix="are-native-db-") as folder:
            db = Path(folder) / "weights.sqlite3"
            with patch.dict(os.environ, {"ARE_LEARNING_DB": str(db)}):
                expected = run_model(self.binary, request, workers=1, repeats=2)
                self.assertEqual(expected["receipt"]["workers"], 1)
                outputs = [run_model(self.binary, request, workers="auto", repeats=2)
                           for _ in range(4)]
                for row in outputs:
                    self.assertEqual(row["receipt"]["workers"], 1)
                    for name in ("frames", "resolved", "depth"):
                        np.testing.assert_array_equal(row[name], expected[name])
                    self.assertEqual(row["learning"]["outcome"], "matched")
                prof = next(p for p in LocalLearner(db).status()
                            if p["scope"].get("stage") == "native-model")
                self.assertEqual(prof["pairs"], 4)
                original_request_hash = hashlib.sha256(request.read_bytes()).hexdigest()
                self.assertEqual(prof["scope"]["request_sha256"], original_request_hash)
                key = json.dumps(prof["scope"], separators=(",", ":"), sort_keys=True)
                with closing(sqlite3.connect(db)) as conn, conn:
                    conn.execute("UPDATE models SET runs=5,pairs=4,reference_ns=10000,"
                                 "candidate_ns=1000,log_gain=?,recent_wins=15,blocked=0 WHERE scope=?",
                                 (math.log(10), key))
                winner = run_model(self.binary, request, workers="auto", repeats=2)
                self.assertEqual(winner["learning"]["served"], "candidate")
                self.assertEqual(winner["receipt"]["workers"], 2)
                for name in ("frames", "resolved", "depth"):
                    np.testing.assert_array_equal(winner[name], expected[name])
                # An explicit worker contract must never be silently modified.
                explicit = run_model(self.binary, request, workers=1, repeats=2)
                self.assertEqual(explicit["receipt"]["workers"], 1)
                self.assertEqual(explicit["learning"]["served"], "reference")
                # A second source of the same byte length must never inherit the
                # candidate proof from an earlier request. The native worker must
                # validate output parity independently on the new request.
                initial_size = request.stat().st_size
                write_scene(request, [dict(asset=asset, clip=None)], [1.0],
                            pixels=32, tile=16)
                self.assertEqual(request.stat().st_size, initial_size)
                self.assertNotEqual(hashlib.sha256(request.read_bytes()).hexdigest(),
                                    original_request_hash)
                changed = run_model(self.binary, request, workers="auto", repeats=2)
                self.assertEqual(changed["learning"]["served"], "reference")
                self.assertEqual(changed["learning"]["outcome"], "matched")
                self.assertNotEqual(changed["learning"]["scope"], winner["learning"]["scope"])

    def test_animated_pose_auto_weights_prove_actual_vertex_parity(self):
        from software_gpu.research.model_probe import load_asset, write_scene, run_model
        from software_gpu.tests.fixtures.model_fixture import make_glb
        with tempfile.TemporaryDirectory(prefix="are-native-pose-db-") as folder:
            db = Path(folder) / "weights.sqlite3"
            src = Path(folder) / "animated.glb"
            metadata = make_glb(src)
            asset = load_asset(src, metadata)
            request = Path(folder) / "pose.aremdl"
            write_scene(request, [dict(asset=asset, clip=0)], [0.0, 1.0],
                        pixels=32, tile=16)
            with patch.dict(os.environ, {"ARE_LEARNING_DB": str(db)}):
                expected = run_model(self.binary, request, workers=1,
                                     repeats=2, mode="pose")
                candidate = run_model(self.binary, request, workers=2,
                                      repeats=2, mode="pose")
                for a, b in zip(expected["poses"], candidate["poses"]):
                    for x, y in zip(a, b):
                        np.testing.assert_array_equal(x, y)
                for _ in range(4):
                    out = run_model(self.binary, request, workers="auto",
                                    repeats=2, mode="pose")
                    self.assertEqual(out["learning"]["outcome"], "matched")
                    self.assertEqual(out["learning"]["served"], "reference")
                profile, = [p for p in LocalLearner(db).status()
                            if p["scope"].get("stage") == "native-model"
                            and p["scope"].get("mode") == "pose"]
                self.assertEqual(profile["pairs"], 4)
