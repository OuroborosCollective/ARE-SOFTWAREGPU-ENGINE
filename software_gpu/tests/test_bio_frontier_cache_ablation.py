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

    def test_static_frontier_uses_disjoint_chunks_and_matches_oracle(self):
        self.assertEqual(ABLATIONS["default"], ())
        self.assertEqual(ABLATIONS["static-frontier-chunks"],
                         ("-DARE_BIO_STATIC_FRONTIER_CHUNKS=1",))
        width, height, tile = 40, 32, 1
        scene = sparse_scene()
        reference, final = renderer_oracle(width, height, scene)
        n_tiles = width * height
        n_chunks = (n_tiles + 31) // 32
        with tempfile.TemporaryDirectory(prefix="are-static-frontier-") as tmp:
            executable, build = build_bio_workrooms(tmp, ablation="static-frontier-chunks")
            self.assertEqual(build["flags"][-1], "-DARE_BIO_STATIC_FRONTIER_CHUNKS=1")
            for workers in (1, 2, 4, 8):
                with self.subTest(workers=workers):
                    out = run_bio_workrooms(executable, descriptor(width, height, tile, 17),
                                            scene, workers, 3, "combined")
                    expected = [sum(min(32, n_tiles - chunk * 32)
                                    for chunk in range(w, n_chunks, workers))
                                for w in range(workers)]
                    self.assertEqual(out["receipt"]["waves"][1]["worker_jobs"], expected)
                    self.assertEqual(out["resolved"], reference.color_buffer.tobytes())
                    self.assertEqual(out["rgba"], final.color_buffer.tobytes())
                    self.assertEqual(out["depth"],
                                     final.depth_buffer.astype("<f4").tobytes())
                    self.assertTrue(out["receipt"]["handoff_ready"])
