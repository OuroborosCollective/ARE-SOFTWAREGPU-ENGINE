"""RED/GREEN: BMP exporter must consult persisted local weights, not only upstream pixels."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.learning import LocalLearner


class AllRouteLearningRedGreen(unittest.TestCase):
    def test_bmp_bytes_use_local_weight_store(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "learn.sqlite3"
            with patch.dict(os.environ, {"ARE_LEARNING_DB": str(db)}):
                fb = Framebuffer(17, 13)
                fb.clear(17, 66, 201)
                before = fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()
                encoded = fb.to_bmp_bytes()
                self.assertEqual(encoded[:2], b"BM")
                self.assertEqual((fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()), before)
                self.assertEqual(fb.last_export_learning_receipt["served"], "reference")
                self.assertEqual(LocalLearner(db).status()[0]["scope"]["stage"], "bmp-byte-export")
