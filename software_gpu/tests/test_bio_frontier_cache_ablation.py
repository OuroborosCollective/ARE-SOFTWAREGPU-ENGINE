"""Compile and execute real C++17 bio-frontier ablations, exact framebuffer parity."""
import os
import tempfile
import unittest

from software_gpu.research.bio_workrooms import ABLATIONS, build_bio_workrooms, run_bio_workrooms
from software_gpu.research.workrooms import descriptor
from software_gpu.tests.test_bio_workrooms import sparse_scene
from software_gpu.tests.test_workrooms import renderer_oracle, scene_fixture


@unittest.skipUnless(os.environ.get('ARE_BIO_CACHE_ABLATION_TEST') == '1',
                     'Dedicated native cache-ablation CI job')
class TestBioFrontierAblations(unittest.TestCase):
    def test_unknown_variant_rejected_before_file_access(self):
        with self.assertRaisesRegex(ValueError, "ROOM_ABLATION_UNKNOWN"):
            build_bio_workrooms("not-a-directory", ablation="../../untrusted")

    def test_real_native_variants_match_python_oracle_across_workers(self):
        cases = [(31,29,4,1,scene_fixture()), (31,29,4,2,scene_fixture()),
                 (37,35,1,4,sparse_scene()), (19,17,4,8,sparse_scene())]
        with tempfile.TemporaryDirectory(prefix="are-frontier-ablation-") as tmp:
            for name in ABLATIONS:
                with self.subTest(ablation=name):
                    exe, build = build_bio_workrooms(f"{tmp}/{name}", ablation=name)
                    self.assertEqual(build["ablation"], name)
                    self.assertEqual(len(build["binary_sha256"]), 64)
                    for width,height,tile,workers,scene in cases:
                        with self.subTest(ablation=name,tile=tile,workers=workers):
                            expected_resolved, expected_final = renderer_oracle(width,height,scene)
                            result = run_bio_workrooms(exe,descriptor(width,height,tile,17),
                                                       scene,workers,2,"combined")
                            self.assertEqual(result["resolved"],expected_resolved.color_buffer.tobytes())
                            self.assertEqual(result["rgba"],expected_final.color_buffer.tobytes())
                            self.assertEqual(result["depth"],expected_final.depth_buffer.astype("<f4").tobytes())
                            self.assertEqual(result["receipt"]["workers"],workers)
                            self.assertTrue(result["receipt"]["handoff_ready"])
