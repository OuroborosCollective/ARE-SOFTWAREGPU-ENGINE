"""Native asset benchmarks must be source-bound and fail closed offline."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.benchmark_owner_lods import OwnerBenchmarkError, load_manifest, read_asset, stats, validate_manifest
from tools.owner_lod_native_normals import repair_lod
from software_gpu.tests.test_owner_lod_native_normals import simple_glb


class TestOwnerLodBenchmarkManifest(unittest.TestCase):
    def test_manifest_has_exact_owner_source_sha_and_expected_lods(self):
        path = Path(__file__).resolve().parents[2] / 'evidence/owner-lod-native-manifest-20261016.json'
        models = load_manifest(path)
        self.assertEqual([m['name'] for m in models], ['forest-lord', 'emerald-grass'])
        for model in models:
            self.assertEqual([r['label'] for r in model['variants']], ['original', 'lod0', 'lod1', 'lod2'])
            self.assertEqual([r['triangles'] for r in model['variants'][1:]], [30000,12000,4000])

    def test_rejects_bad_manifest_and_unsafe_file_names(self):
        path = Path(__file__).resolve().parents[2] / 'evidence/owner-lod-native-manifest-20261016.json'
        data = json.loads(path.read_text())
        for mutate in [lambda d: d['models'].pop(),
                       lambda d: d['models'][0]['variants'][1].update(file='../escape.glb'),
                       lambda d: d['models'][0]['variants'][1].update(sha256='notsha'),
                       lambda d: d['models'][0]['variants'][1].update(triangles=True),
                       lambda d: d['models'][0]['variants'][0].update(label='lod0'),
                       lambda d: d['models'][1].update(name='forest-lord')]:
            with self.subTest(mutate=mutate):
                clone = copy.deepcopy(data)
                mutate(clone)
                with self.assertRaises(OwnerBenchmarkError):
                    validate_manifest(clone)

    def test_read_asset_requires_correct_real_file_sha_and_triangle_count(self):
        raw = simple_glb()
        fixed, _ = repair_lod(raw, hashlib.sha256(raw).hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'good.glb'
            file.write_bytes(fixed)
            got = read_asset(file, hashlib.sha256(fixed).hexdigest(), 1)
            self.assertEqual(got['triangles'], 1)
            with self.assertRaisesRegex(OwnerBenchmarkError,'OWNER_BENCH_SHA'):
                read_asset(file, '0' * 64, 1)
            with self.assertRaisesRegex(OwnerBenchmarkError,'OWNER_BENCH_TRIANGLES'):
                read_asset(file, hashlib.sha256(fixed).hexdigest(), 2)

    def test_stats_are_actual_samples_with_robust_spread(self):
        result = stats([1,2,3,4,20])
        self.assertEqual(result['n'],5)
        self.assertEqual(result['median_ms'],3)
        self.assertEqual(result['mad_ms'],1)
        self.assertEqual(result['minimum_ms'],1)
        self.assertEqual(result['maximum_ms'],20)
        with self.assertRaises(OwnerBenchmarkError):
            stats([float('nan'),2,3])


if __name__ == '__main__':
    unittest.main()
