"""Real C++17 AREMDL03 smoke: missing normals are repaired before PBR import.

No owner model is committed to the repository. The tiny on-the-fly GLB uses
actual embedded PNG/PBR maps and exercises native color/depth worker parity.
"""
import hashlib
from pathlib import Path
import tempfile
import unittest
import numpy as np

from software_gpu.research.model_probe import load_asset, write_scene, run_model, build_model_probe
from software_gpu.tests.fixtures.model_fixture import make_glb
from tools.owner_lod_native_normals import repair_lod


class TestOwnerLodNativeBridge(unittest.TestCase):
    def test_repaired_static_pbr_glb_runs_native_cpp17_with_full_buffer_parity(self):
        with tempfile.TemporaryDirectory(prefix='are-lod-native-') as temp:
            root = Path(temp)
            raw_path = root / 'no-normals.glb'
            def remove_normals(doc, binary):
                # Real GLB with embedded PBR images, removing just the attribute.
                del doc['meshes'][0]['primitives'][0]['attributes']['NORMAL']
            raw_meta = make_glb(raw_path, surface=True, static=True, mutate=remove_normals)
            with self.assertRaisesRegex(ValueError, 'MODEL_SURFACE_ATTRIBUTES'):
                load_asset(raw_path, raw_meta, profile='pbr')
            converted, receipt = repair_lod(raw_path.read_bytes(), raw_meta['sha256'])
            fixed_path = root / 'normals-added.glb'
            fixed_path.write_bytes(converted)
            meta = {'sha256': receipt['after_sha256'], 'bytes': len(converted)}
            asset = load_asset(fixed_path, meta, profile='pbr')
            self.assertEqual(len(asset['faces']), 1)
            self.assertEqual(len(asset['normals']), 3)
            self.assertEqual(len(asset['textures']), 3)
            np.testing.assert_allclose(asset['normals'], np.array([[0, 0, 1]]*3), atol=1e-6)
            camera = dict(eye=[1.33, 2.33, 6], target=[1.33, 2.33, 3],
                          up=[0, 1, 0], fov_y_degrees=55, near=.1, far=12)
            request = root / 'native-pbr.aremdl'
            request_receipt = write_scene(request, [dict(asset=asset, clip=None)],
                                          [0., 0.], pixels=64, tile=16,
                                          projection='perspective', camera=camera,
                                          render_profile='pbr')
            self.assertEqual(request_receipt['protocol'], 'are.model-input.v3')
            exe, build_receipt = build_model_probe(root / 'native')
            self.assertFalse(build_receipt['python_in_runtime'])
            one = run_model(exe, request, workers=1, repeats=2,
                            render_profile='pbr', timeout=120)
            two = run_model(exe, request, workers=2, repeats=2,
                            render_profile='pbr', timeout=120)
            for key in ('frames', 'resolved', 'depth'):
                np.testing.assert_array_equal(one[key], two[key])
            self.assertTrue(two['receipt']['full_buffer_parity'])
            self.assertGreater(sum(two['receipt']['sample_writes']), 0)
            self.assertEqual(two['receipt']['render_profile'], 'pbr')
            self.assertEqual(two['receipt']['textures'], 3)
            self.assertFalse(two['receipt']['hardware_gpu_submitted'])


if __name__ == '__main__':
    unittest.main()
