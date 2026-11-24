"""Real importer, framebuffer and SQLite regressions for emissive surfaces and bloom."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from software_gpu.graphics.display_bloom import apply_display_bloom
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.postprocess import GamingPostProcessing
from software_gpu.learning import LocalLearner
from software_gpu.research.model_probe import load_asset
from software_gpu.tests.fixtures.model_fixture import make_glb


class EmissionTests(unittest.TestCase):
    def import_surface(self, extension, *, name='KHR_materials_emissive_strength',
                       factor=(.25, .5, 1), profile='pbr'):
        def author(doc, binary):
            doc['extensionsUsed'] = doc['extensionsRequired'] = [name]
            doc['materials'][0].update(extensions={name: extension}, emissiveFactor=factor)
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'surface.glb'
            entry = make_glb(source, author, static=True, surface=True)
            return load_asset(source, entry, profile=profile)

    def test_multiplier_default_and_zero(self):
        for ext, expected in [({}, [.25, .5, 1]), ({'emissiveStrength': 4}, [1, 2, 4]),
                              ({'emissiveStrength': 0}, [0, 0, 0])]:
            self.assertEqual(self.import_surface(ext)['material']['emissive'], expected)

    def test_reject_invalid_and_unsupported(self):
        for strength in [-1, True, '2', float('inf'), float('nan'), 10001]:
            with self.subTest(strength=strength), self.assertRaises(ValueError):
                self.import_surface({'emissiveStrength': strength})
        with self.assertRaisesRegex(ValueError, 'MODEL_EMISSIVE'):
            self.import_surface({}, factor=(0, 2, 0))
        with self.assertRaisesRegex(ValueError, 'EXTENSION'):
            self.import_surface({}, name='KHR_materials_transmission')
        with self.assertRaisesRegex(ValueError, 'EXTENSION'):
            self.import_surface({}, profile='diagnostic')


class BloomTests(unittest.TestCase):
    @staticmethod
    def impulse():
        fb = Framebuffer(17, 67)
        fb.clear(0, 0, 0, 255)
        fb.color_buffer[32, 8] = 255
        fb.depth_buffer[...] = np.arange(17 * 67, dtype=np.float32).reshape(67, 17) / (17 * 67)
        return fb

    def test_halo_falloff_symmetry_and_preserved_buffers(self):
        fb = self.impulse()
        fb.color_buffer[4, 4] = (255, 255, 255, 0)
        with patch.dict('os.environ', ARE_LEARNING_DB='off'):
            out = apply_display_bloom(fb)
            zero = apply_display_bloom(fb, intensity=0)
        pixels = out.color_buffer[..., 0]
        radial = pixels[32, 8:14].tolist()
        self.assertTrue(all(a > b for a, b in zip(radial, radial[1:])), radial)
        np.testing.assert_array_equal(radial, pixels[32:38, 8])
        np.testing.assert_array_equal(radial, pixels[32, 8:2:-1])
        self.assertEqual(pixels[4, 5], 0)  # no emission from a fully transparent texel
        np.testing.assert_array_equal(out.depth_buffer, fb.depth_buffer)
        np.testing.assert_array_equal(out.color_buffer[..., 3], fb.color_buffer[..., 3])
        np.testing.assert_array_equal(zero.color_buffer, fb.color_buffer)

    def test_gaming_entry_produces_a_calibrated_preview(self):
        fb = self.impulse()
        with patch.dict('os.environ', ARE_LEARNING_DB='off'):
            out = GamingPostProcessing.apply_bloom_and_hdr(fb, quality_bloom=True)
        self.assertEqual(out.bloom_quality['weight_state'], 'ephemeral')
        self.assertGreater(out.color_buffer[32, 9, 0], 0)
        np.testing.assert_array_equal(out.depth_buffer, fb.depth_buffer)

    def test_fit_limits_clipping_and_reloads_exact_weight(self):
        fb = Framebuffer(64, 64)
        fb.clear(248, 185, 90, 255)
        fb.color_buffer[::3, ::3, 0] = 254
        with tempfile.TemporaryDirectory() as root, patch.dict(
                'os.environ', ARE_LEARNING_DB=str(Path(root) / 'model.db')):
            cold = apply_display_bloom(fb)
            warm = apply_display_bloom(fb)
        fit = cold.bloom_quality
        self.assertGreater(fit['clipped_requested'], fit['budget'])
        self.assertLessEqual(fit['clipped_selected'], fit['budget'])
        actual = np.count_nonzero((fb.color_buffer[..., :3] < 255) & (cold.color_buffer[..., :3] == 255))
        self.assertEqual(actual, fit['clipped_selected'])
        self.assertTrue(0 < fit['gain_step'] < fit['gain_steps'])
        self.assertEqual(fit['weight_state'], 'fitted')
        self.assertEqual(warm.bloom_quality['weight_state'], 'reused')
        np.testing.assert_array_equal(cold.color_buffer, warm.color_buffer)

    def test_learning_matches_across_strip_boundary_and_persists(self):
        import hashlib
        fb = self.impulse()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'learning.sqlite3'
            with patch.dict('os.environ', ARE_LEARNING_DB=str(path)):
                out = apply_display_bloom(fb)
            record = LocalLearner(path, create=False).samples(1)[0]
            digest = hashlib.sha256(out.color_buffer)
            digest.update(out.depth_buffer)
            self.assertEqual(record['outcome'], 'matched')
            self.assertEqual(record['candidate_hash'], digest.hexdigest())
            self.assertEqual(record['reference_hash'], digest.hexdigest())
            self.assertEqual(record['id'], out.last_bloom_learning_receipt['sample_id'])
