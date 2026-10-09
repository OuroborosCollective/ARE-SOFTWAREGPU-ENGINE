import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from software_gpu.training.metrics import MetricRecorder


class TrainingMetricsTests(unittest.TestCase):
    def recorder(self, directory, name="metrics"):
        return MetricRecorder(Path(directory) / name, "a" * 40, "b" * 40)

    def test_real_rasterizer_deterministic_hash_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("first", "second"):
                recorder = self.recorder(directory, name)
                self.assertFalse(recorder.observe(0, {"learning_rate": 0.0001}))
                self.assertFalse((recorder.output / "loss.bmp").exists())
                recorder.observe(5, {"loss": 2.75})
                recorder.observe(10, {"loss": 1.25})
                receipt = json.loads((recorder.output / "render_receipt.json").read_text())
                self.assertEqual(receipt["observations"], 2)
                for file, key in [("loss.jsonl", "loss_jsonl_sha256"),
                                  ("loss.bmp", "image_sha256")]:
                    self.assertEqual(hashlib.sha256((recorder.output / file).read_bytes()).hexdigest(), receipt[key])
                self.assertEqual((recorder.output / "loss.bmp").read_bytes()[:2], b"BM")
                self.assertFalse(receipt["model_release_accepted"])
            self.assertEqual((Path(directory) / "first/loss.bmp").read_bytes(),
                             (Path(directory) / "second/loss.bmp").read_bytes())

    def test_reject_invalid_observations_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = self.recorder(directory)
            for step, loss in [(1, float("nan")), (1, float("inf")), (1, -1), (-1, 1), (True, 1)]:
                with self.assertRaises(ValueError):
                    recorder.observe(step, {"loss": loss})
            self.assertEqual(recorder.history, [])
            recorder.observe(1, {"loss": 0.0})
            with self.assertRaises(ValueError):
                recorder.observe(1, {"loss": 1.0})

    def test_no_overwrite_or_mutable_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            self.recorder(directory)
            with self.assertRaises(FileExistsError):
                self.recorder(directory)
            with self.assertRaises(ValueError):
                MetricRecorder(Path(directory) / "invalid", "main", "b" * 40)


if __name__ == "__main__":
    unittest.main()
