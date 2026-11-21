"""Native AREMDL03 lab: real worker output and source-pinned three-view checks."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from software_gpu.tests.fixtures.model_fixture import make_glb
from tools.visual_asset_lab_native import render_native_asset_lab

CAMERA = dict(eye=[1.33, 2.33, 6], target=[1.33, 2.33, 3],
              up=[0, 1, 0], fov_y_degrees=55, near=.1, far=12)


def sample(path, *, mutate=None, name='lod0'):
    identity = make_glb(path, static=True, surface=True, mutate=mutate)
    return dict(id=name, path=str(path), sha256=identity['sha256'], bytes=identity['bytes'])


class TestVisualAssetLabNative(unittest.TestCase):
    def test_two_revisions_use_real_cpp17_pbr_and_identical_camera_and_fit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a = sample(root / 'first.glb')
            def material_change(doc, binary):
                doc['materials'][0]['pbrMetallicRoughness']['roughnessFactor'] = .35
            b = sample(root / 'second.glb', mutate=material_change, name='lod1')
            receipt = render_native_asset_lab([a, b], root / 'views',
                                              camera=CAMERA, pixels=64, repeats=2)
            self.assertEqual(receipt['protocol'], 'are.visual-asset-lab.native.v1')
            self.assertEqual(receipt['camera'], CAMERA)
            self.assertEqual(receipt['comparability']['status'], 'same_native_fit_and_camera')
            self.assertEqual(len(receipt['assets']), 2)
            self.assertNotEqual(a['sha256'], b['sha256'])
            for asset in receipt['assets']:
                self.assertEqual(asset['renderer']['protocol'], 'are.model-probe.receipt.v2')
                self.assertEqual(asset['renderer']['render_profile'], 'pbr')
                self.assertEqual(asset['renderer']['full_buffer_parity'], True)
                self.assertEqual(asset['renderer']['worker_counts'], [1, 2])
                self.assertTrue(any(n > 0 for n in asset['renderer']['sample_writes']))
                self.assertEqual(asset['shadow_status'], 'not_implemented')
                self.assertEqual(asset['normal_status'], 'source_normals')
                self.assertTrue(asset['materials'])
                self.assertEqual(len(asset['materials'][0]['sha256']), 64)
                self.assertEqual(len(asset['embedded_images']), 3)
                frame = root / 'views' / asset['id']
                images = asset['artifacts']
                for key in ('beauty_png', 'beauty_bmp', 'rgba8', 'depth_f32le',
                            'wireframe_svg', 'uv_seams_svg'):
                    payload = (frame / images[key]['filename']).read_bytes()
                    self.assertEqual(hashlib.sha256(payload).hexdigest(),
                                     images[key]['sha256'])
                with Image.open(frame / images['beauty_png']['filename']) as im:
                    decoded = np.asarray(im.convert('RGBA'))
                self.assertEqual(decoded.tobytes(),
                                 (frame / images['rgba8']['filename']).read_bytes())
                native_depth = (frame / images['depth_f32le']['filename']).read_bytes()
                self.assertEqual(len(native_depth), 64 * 64 * 4)
                self.assertTrue(np.isfinite(np.frombuffer(native_depth, dtype='<f4')).all())
                self.assertNotEqual(images['beauty_png']['sha256'], images['rgba8']['sha256'])
                self.assertEqual(asset['camera'], CAMERA)
                self.assertIn(b'<svg', (frame / 'wireframe.svg').read_bytes())
            self.assertEqual(json.loads((root / 'views' / 'receipt.json').read_text()), receipt)

    def test_wrong_source_sha_or_uri_is_rejected_without_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            original = sample(root / 'source.glb')
            bad = dict(original, sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'MODEL_SOURCE_HASH'):
                render_native_asset_lab([bad], root / 'wrong', camera=CAMERA, pixels=64)
            self.assertFalse((root / 'wrong').exists())
            uri = dict(original, path='https://untrusted.example/x.glb')
            with self.assertRaisesRegex(ValueError, 'ASSET_LAB_LOCAL_FILE'):
                render_native_asset_lab([uri], root / 'uri', camera=CAMERA, pixels=64)
            self.assertFalse((root / 'uri').exists())

    def test_external_image_uri_fails_closed_before_render(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            def external(doc, binary):
                doc['images'][0]['uri'] = '../../private/texture.png'
            src = sample(root / 'external.glb', mutate=external)
            with self.assertRaisesRegex(ValueError, 'MODEL_EXTERNAL_IMAGE'):
                render_native_asset_lab([src], root / 'out', camera=CAMERA, pixels=64)
            self.assertFalse((root / 'out').exists())

    def test_second_revision_with_different_native_fit_is_marked_noncomparable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a = sample(root / 'first.glb')
            def moved(doc, binary):
                doc['nodes'][0]['matrix'][0] = 2
            b = sample(root / 'moved.glb', mutate=moved, name='lod1')
            receipt = render_native_asset_lab([a, b], root / 'out', camera=CAMERA, pixels=64)
            self.assertEqual(receipt['comparability']['status'],
                             'same_camera_different_native_fit_not_visually_equivalent')
            self.assertFalse(receipt['comparability']['native_auto_fit_equal'])
            self.assertEqual(len(receipt['assets']), 2)

    def test_output_cannot_reuse_existing_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a = sample(root / 'first.glb')
            out = root / 'views'
            out.mkdir()
            (out / 'old.txt').write_text('existing')
            with self.assertRaisesRegex(ValueError, 'ASSET_LAB_OUTPUT'):
                render_native_asset_lab([a], out, camera=CAMERA, pixels=64)
            self.assertEqual((out / 'old.txt').read_text(), 'existing')
