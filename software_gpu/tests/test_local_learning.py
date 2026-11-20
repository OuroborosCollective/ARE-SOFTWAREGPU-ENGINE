"""Contract and real raster/encoder regressions for the local authoring tuner."""
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from software_gpu.benchmarks.compare_tile_backends import FlatShader, make_fixture
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.learning import LocalLearner, Model, configured_learner, scope_key


class LocalLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "learning.sqlite3"
        self.env = patch.dict(os.environ, {"ARE_LEARNING_DB": str(self.db)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_update_rule_and_minimum_paired_evidence(self):
        # Arithmetic unit test in nanoseconds; these numbers are not benchmark data.
        model = Model()
        for _ in range(3):
            model.update(2000, 1000, "matched")
            self.assertFalse(model.prefers_candidate())
        model.update(2000, 1000, "matched")
        self.assertTrue(model.prefers_candidate())
        model.update(None, 50000, "single")
        self.assertFalse(model.prefers_candidate())
        self.assertEqual((model.runs, model.pairs), (5, 4))

    def test_exact_raster_and_restart(self):
        verts, indices = make_fixture(4, .55)
        def draw(environment, shader):
            with patch.dict(os.environ, {"ARE_LEARNING_DB": environment}):
                fb = Framebuffer(43, 39)
                fb.clear(14, 33, 61, 200, .9)
                fb.depth_buffer[::3, ::3] = 0.
                r = SoftwareRasterizer(fb, num_threads=1, tile_size=8)
                try:
                    r.draw_mesh(verts, indices, shader)
                    return (fb.color_buffer.tobytes(), fb.depth_buffer.tobytes(),
                            r.last_learning_receipt)
                finally:
                    r.executor.shutdown()
        expected = draw("off", VertexColorShader())
        self.assertIsNone(expected[2])
        for _ in range(6):
            color, depth, receipt = draw(str(self.db), VertexColorShader())
            self.assertEqual((color, depth), expected[:2])
        profiles = LocalLearner(self.db).status()
        self.assertEqual((profiles[0]["runs"], profiles[0]["pairs"]), (6, 4))
        self.assertGreater(profiles[0]["reference_ns"], 0)
        self.assertGreater(profiles[0]["candidate_ns"], 0)
        self.assertEqual(receipt["outcome"], "single")
        self.assertEqual(draw(str(self.db), FlatShader())[2]["outcome"], "observe")
        self.assertEqual(len(LocalLearner(self.db).samples()), 7)

    def test_mismatch_quarantines_and_failed_reference_never_trains(self):
        learner = LocalLearner(self.db)
        key = scope_key(stage="test", profile="negative-control")
        def render(alt):
            return b"wrong" if alt else b"original"
        digest = lambda data: hashlib.sha256(data).hexdigest()
        result, receipt = learner.execute(key, render, digest)
        self.assertEqual((result, receipt["outcome"]), (b"original", "mismatch"))
        self.assertTrue(learner.status()[0]["blocked"])
        routes = []
        def again(alt):
            routes.append(alt)
            return render(alt)
        self.assertEqual(learner.execute(key, again, digest)[0], b"original")
        self.assertEqual(routes, [False])
        def broken(alt):
            raise ValueError("failed reference")
        with self.assertRaises(ValueError):
            learner.execute(key, broken, digest)
        self.assertEqual(len(learner.samples()), 2)
        self.assertNotEqual(learner.samples()[-1]["reference_hash"], learner.samples()[-1]["candidate_hash"])

    def test_candidate_failure_returns_reference_and_blocks_retrial(self):
        learner = LocalLearner(self.db)
        key = scope_key(stage="test", profile="exception")
        routes = []
        def execute(alt):
            routes.append(alt)
            if alt:
                raise ValueError("candidate cannot finish")
            return b"valid"
        with self.assertWarnsRegex(RuntimeWarning, "candidate rejected"):
            frame, receipt = learner.execute(key, execute, lambda b: hashlib.sha256(b).hexdigest())
        self.assertEqual((frame, receipt["outcome"], routes), (b"valid", "candidate-error", [False, True]))
        self.assertTrue(learner.status()[0]["blocked"])

    def test_dataset_retention_and_restart_in_another_interpreter(self):
        learner = LocalLearner(self.db)
        cold = scope_key(stage="old")
        live = scope_key(stage="new")
        # A reduced retention window tests the storage boundary without timing assertions.
        with patch("software_gpu.learning.MAX_SAMPLES", 3):
            learner.execute(cold, lambda _: 1)
            for _ in range(3):
                learner.execute(live, lambda _: 1)
        self.assertEqual([m["scope"]["stage"] for m in learner.status()], ["new"])
        output = subprocess.check_output([sys.executable, "-c",
            "from software_gpu.learning import configured_learner; "
            "s=configured_learner(); print(len(s.samples()),s.status()[0]['runs'])"], text=True)
        self.assertEqual(output.strip(), "3 3")

    def test_disabled_mode_creates_no_store_and_status_rejects_foreign_db(self):
        with patch.dict(os.environ, {"ARE_LEARNING_DB": "", "XDG_STATE_HOME": self.tmp.name}):
            self.assertIsNone(configured_learner())
            self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        self.db.touch()
        with self.assertRaises(ValueError):
            LocalLearner(self.db, create=False)
        self.assertEqual(self.db.stat().st_size, 0)

    def test_concurrent_process_safe_updates_and_unavailable_store(self):
        key = scope_key(stage="test", profile="counts")
        def job(_):
            return LocalLearner(self.db).execute(key, lambda alt: b"value", None)
        with ThreadPoolExecutor(4) as workers:
            self.assertEqual(len(list(workers.map(job, range(12)))), 12)
        self.assertEqual(LocalLearner(self.db).status()[0]["runs"], 12)
        with TemporaryDirectory() as bad:
            with patch.dict(os.environ, {"ARE_LEARNING_DB": bad}), self.assertWarns(RuntimeWarning):
                self.assertIsNone(configured_learner())
        other = Path(self.tmp.name) / "other.db"
        with sqlite3.connect(other) as con:
            con.execute("CREATE TABLE important(value)")
        with self.assertRaises(ValueError):
            LocalLearner(other)
        with sqlite3.connect(other) as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 0)


@unittest.skipUnless(shutil.which("ffmpeg-9.1") or shutil.which("ffmpeg"), "requires real FFmpeg")
class VideoLearningTests(unittest.TestCase):
    def test_real_video_entrypoint_keeps_pixels_and_count(self):
        if os.name == "nt" and not shutil.which("ffprobe"):
            self.skipTest("requires ffprobe")
        from software_gpu.integrations.render_video import encode_frames, media_binaries
        with TemporaryDirectory() as folder:
            root = Path(folder)
            db = root / "video.sqlite3"
            frames, source = [], []
            for i in range(3):
                rgb = bytes([17+i, 40, 30]) * (17*15)
                p = root / f"source-{i}.ppm"
                p.write_bytes(b"P6\n17 15\n255\n" + rgb)
                frames.append(p)
                source.append(rgb)
            ffmpeg, ffprobe = media_binaries()
            with patch.dict(os.environ, {"ARE_LEARNING_DB": str(db)}):
                out = root / "frames.mkv"
                result = encode_frames(out, frames, Fraction(12), ffmpeg, ffprobe)
                self.assertEqual(result["learning"]["outcome"], "matched")
                self.assertEqual(int(result["nb_read_frames"]), 3)
                raw = subprocess.check_output([ffmpeg, "-v", "error", "-i", out,
                                               "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
                self.assertEqual(raw, b"".join(source))
                with self.assertRaises((ValueError, FileExistsError)):
                    encode_frames(out, frames, Fraction(12), ffmpeg, ffprobe)
                frames[0].write_bytes(b"invalid")
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    encode_frames(root / "bad.mkv", frames, Fraction(12), ffmpeg, ffprobe)
                self.assertFalse((root / "bad.mkv").exists())
                self.assertEqual(len(LocalLearner(db).samples()), 1)
