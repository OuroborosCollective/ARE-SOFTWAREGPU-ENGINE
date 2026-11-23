"""Real C++ draw commands: inherited local SQLite weight policy.

A manually edited weight is an explicit *selection* test, never performance
evidence. All matched profiles require actual C++ RGBA8 + float32 depth +
raster counters; nonmatching results must fail closed.
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

from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.drivers.native_bridge import AREDriverBridge, build_driver_bridge
from software_gpu.drivers.command_submission import record_native_draws, submit_native_draws
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.geometry import prepare_triangles
from software_gpu.graphics.native_raster import pack_triangles
from software_gpu.learning import LocalLearner, scope_key


class NativeCommandWeightCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver_dir = tempfile.TemporaryDirectory(prefix="are-command-weight-driver-")
        binary, build = build_driver_bridge(Path(cls.driver_dir.name))
        cls.bridge = AREDriverBridge(binary, build["binary_sha256"])
        mesh, faces = make_fixture(4, .8)
        cls.packed = pack_triangles(prepare_triangles(mesh, faces, VertexColorShader(), 32, 24))
        cls.packet = record_native_draws([cls.packed, cls.packed])

    @classmethod
    def tearDownClass(cls):
        import sys
        if sys.platform == "win32":
            cls.driver_dir._finalizer.detach()  # ctypes Windows keeps actual DLL mapped
        else:
            cls.driver_dir.cleanup()

    def setUp(self):
        self.store = tempfile.TemporaryDirectory(prefix="are-command-weight-db-")
        self.addCleanup(self.store.cleanup)
        self.db = Path(self.store.name) / "weights.sqlite3"

    @staticmethod
    def frame():
        frame = Framebuffer(32, 24)
        frame.clear(7, 23, 43)
        return frame

    def test_canonical_sqlite_weights_train_using_actual_native_outputs(self):
        with patch.dict(os.environ, {"ARE_LEARNING_DB": "off"}):
            baseline = self.frame()
            baseline_receipt = submit_native_draws(self.bridge, baseline, self.packet)
        self.assertEqual(baseline_receipt["native_cpp_calls"], 2)
        self.assertGreater(baseline_receipt["shaded_samples"], 0)
        original = (baseline.color_buffer.tobytes(), baseline.depth_buffer.tobytes())

        # Existing databases and weights must coexist with the new command scope.
        db = LocalLearner(self.db)
        historical = scope_key(stage="raster", variant="historic-reference-only-v1")
        db.execute(historical, lambda _: b"real-history-marker")
        self.assertEqual(db.status()[0]["scope"]["stage"], "raster")

        with patch.dict(os.environ, {"ARE_LEARNING_DB": str(self.db)}):
            for _ in range(4):
                observed = self.frame()
                receipt = submit_native_draws(self.bridge, observed, self.packet)
                self.assertEqual((observed.color_buffer.tobytes(), observed.depth_buffer.tobytes()), original)
                self.assertEqual(receipt["learning"]["outcome"], "matched")
                self.assertEqual(receipt["learning"]["served"], "reference")
                self.assertEqual(receipt["native_cpp_calls"], 2)
                self.assertEqual(receipt["shaded_samples"], baseline_receipt["shaded_samples"])
            rows = db.status()
            active = next(x for x in rows if x["scope"]["stage"] == "native-command-cpp17")
            self.assertEqual(len(rows), 2)
            self.assertEqual(active["scope"]["variant"], "collapsed-native-draw-v1")
            self.assertEqual(active["scope"]["packet_sha256"], self.packet.command_sha256)
            self.assertEqual(active["pairs"], 4)
            self.assertFalse(active["blocked"])
            self.assertEqual(len(db.samples()), 5)

            # Controlled mutation is only to prove that the *existing* saved
            # model is consulted, not that a particular speedup occurred.
            identity = json.dumps(active["scope"], separators=(",", ":"), sort_keys=True)
            with closing(sqlite3.connect(self.db)) as conn, conn:
                conn.execute("UPDATE models SET runs=5,pairs=4,reference_ns=10000,"
                             "candidate_ns=1000,log_gain=?,recent_wins=15,blocked=0 WHERE scope=?",
                             (math.log(10), identity))
            chosen = self.frame()
            receipt = submit_native_draws(self.bridge, chosen, self.packet)
            self.assertEqual(receipt["learning"]["served"], "candidate")
            self.assertEqual(receipt["native_cpp_calls"], 1)
            self.assertEqual((chosen.color_buffer.tobytes(), chosen.depth_buffer.tobytes()), original)
            for name in ("candidate_samples", "covered_samples", "shaded_samples", "rgba_sha256", "depth_sha256"):
                self.assertEqual(receipt[name], baseline_receipt[name])

            # The old raster profile is *not* overwritten or relabelled.
            self.assertEqual(next(x for x in db.status() if x["scope"]["stage"] == "raster")["runs"], 1)

    def test_distinct_packet_produces_distinct_weight_scope(self):
        with patch.dict(os.environ, {"ARE_LEARNING_DB": str(self.db)}):
            first = submit_native_draws(self.bridge, self.frame(), self.packet)
            other = record_native_draws([self.packed])
            second = submit_native_draws(self.bridge, self.frame(), other)
            self.assertNotEqual(first["learning"]["scope"], second["learning"]["scope"])
            self.assertEqual(second["learning"]["served"], "reference")
            self.assertEqual(second["native_cpp_calls"], 1)
            self.assertEqual(len(LocalLearner(self.db).status()), 2)

    def test_invalid_final_command_does_not_train_or_modify_original(self):
        broken = self.packed.copy()
        broken[0, 0] = np.nan
        packet = record_native_draws([self.packed, broken])
        with patch.dict(os.environ, {"ARE_LEARNING_DB": str(self.db)}):
            initial = self.frame()
            before = (initial.color_buffer.tobytes(), initial.depth_buffer.tobytes())
            with self.assertRaisesRegex(ValueError, "ARE_COMMAND_SUBMISSION_REJECTED"):
                submit_native_draws(self.bridge, initial, packet)
            self.assertEqual((initial.color_buffer.tobytes(), initial.depth_buffer.tobytes()), before)
            self.assertEqual(LocalLearner(self.db).samples(), [])

    def test_unconfigured_path_is_unweighted_and_true_native(self):
        with patch.dict(os.environ, {"ARE_LEARNING_DB": "off"}):
            frame = self.frame()
            receipt = submit_native_draws(self.bridge, frame, self.packet)
            self.assertEqual(receipt["native_cpp_calls"], 2)
            self.assertIsNone(receipt["learning"])
            self.assertFalse(receipt["vulkan_icd"])


if __name__ == "__main__":
    unittest.main()
