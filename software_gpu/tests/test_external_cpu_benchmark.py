"""Strict real workload and evidence-classification regression."""
import unittest
import numpy as np

from software_gpu.benchmarks.external_cpu_benchmark import (
    SCENES, compare_images, scene_data, PROTOCOL
)


class TestExternalCpuBenchmark(unittest.TestCase):
    def test_fixture_identity_and_repeatability(self):
        for scene in SCENES:
            a, verts, digest = scene_data(scene)
            b, verts_again, digest_again = scene_data(scene)
            self.assertEqual((a, digest), (b, digest_again))
            np.testing.assert_array_equal(verts, verts_again)
            self.assertGreater(verts.shape[0], 0)
            self.assertEqual(verts.shape[1], 6)
            self.assertTrue(np.isfinite(verts).all())

    def test_noncomparable_msaa_never_gets_speed_ratio(self):
        image = np.zeros((8, 8, 4), dtype=np.uint8)
        image[2:6, 2:6, 0] = 255
        result = compare_images(image, image.copy(), "msaa4")
        self.assertEqual(result["classification"], "NOT_COMPARABLE_MSAA_SAMPLE_POSITIONS")

    def test_mismatched_coverage_not_comparable(self):
        a = np.zeros((8, 8, 4), dtype=np.uint8)
        b = np.zeros((8, 8, 4), dtype=np.uint8)
        a[1:3, 1:3, :3] = 255
        b[5:7, 5:7, :3] = 255
        result = compare_images(a, b, "micro")
        self.assertEqual(result["classification"], "NOT_COMPARABLE_OUTPUT_DIFFERENCE")

    def test_fail_closed_empty_or_invalid_format(self):
        black = np.zeros((8, 8, 4), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, "EMPTY"):
            compare_images(black, black, "micro")
        with self.assertRaisesRegex(ValueError, "FORMAT"):
            compare_images(black, black[:5], "micro")


if __name__ == "__main__":
    unittest.main()
