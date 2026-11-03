"""Deterministic AABB bounds equivalence and paired CPU timing evidence.

This tests the inline ternary operator optimization for AABB bounds calculation.
"""
import json
import statistics
import sys
import time
import unittest
import numpy as np

def _baseline_bounds(s0, s1, s2, y_start, y_end, fb_w):
    min_x = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
    max_x = min(fb_w - 1, int(np.ceil(max(s0[0], s1[0], s2[0]))))
    min_y = max(y_start, int(np.floor(min(s0[1], s1[1], s2[1]))))
    max_y = min(y_end - 1, int(np.ceil(max(s0[1], s1[1], s2[1]))))
    return min_x, max_x, min_y, max_y

def _optimized_bounds(s0, s1, s2, y_start, y_end, fb_w):
    s0x, s1x, s2x = s0[0], s1[0], s2[0]
    s0y, s1y, s2y = s0[1], s1[1], s2[1]

    min_sx = s0x if s0x < s1x else s1x
    min_sx = min_sx if min_sx < s2x else s2x
    max_sx = s0x if s0x > s1x else s1x
    max_sx = max_sx if max_sx > s2x else s2x

    min_sy = s0y if s0y < s1y else s1y
    min_sy = min_sy if min_sy < s2y else s2y
    max_sy = s0y if s0y > s1y else s1y
    max_sy = max_sy if max_sy > s2y else s2y

    min_x = int(np.floor(min_sx))
    min_x = 0 if min_x < 0 else min_x

    max_x = int(np.ceil(max_sx))
    max_x_bound = fb_w - 1
    max_x = max_x_bound if max_x > max_x_bound else max_x

    min_y = int(np.floor(min_sy))
    min_y = y_start if min_y < y_start else min_y

    max_y = int(np.ceil(max_sy))
    max_y_bound = y_end - 1
    max_y = max_y_bound if max_y > max_y_bound else max_y

    return min_x, max_x, min_y, max_y


class TestAABBBoundsPerformance(unittest.TestCase):
    def test_equivalent_scalar_and_inline_bounds(self):
        rng = np.random.default_rng(1234)
        for _ in range(100):
            s0 = rng.uniform(-100, 100, 2).astype(np.float32)
            s1 = rng.uniform(-100, 100, 2).astype(np.float32)
            s2 = rng.uniform(-100, 100, 2).astype(np.float32)
            y_start = rng.integers(0, 50)
            y_end = rng.integers(51, 100)
            fb_w = rng.integers(50, 100)

            baseline = _baseline_bounds(s0, s1, s2, y_start, y_end, fb_w)
            optimized = _optimized_bounds(s0, s1, s2, y_start, y_end, fb_w)

            self.assertEqual(baseline, optimized, f"Failed on inputs: {s0}, {s1}, {s2}, {y_start}, {y_end}, {fb_w}")

    def test_paired_bounds_timing_guard(self):
        rng = np.random.default_rng(1234)

        # Pre-generate inputs
        inputs = []
        for _ in range(1000):
            s0 = rng.uniform(-100, 100, 2).astype(np.float32)
            s1 = rng.uniform(-100, 100, 2).astype(np.float32)
            s2 = rng.uniform(-100, 100, 2).astype(np.float32)
            inputs.append((s0, s1, s2, 0, 480, 640))

        old_ms, new_ms = [], []
        for repetition in range(15):
            order = ((_baseline_bounds, old_ms), (_optimized_bounds, new_ms))
            if repetition % 2:
                order = tuple(reversed(order))
            for fn, samples in order:
                start = time.perf_counter_ns()
                for _ in range(5):
                    for inp in inputs:
                        fn(*inp)
                samples.append((time.perf_counter_ns() - start) / 1e6)

        old_median = statistics.median(old_ms)
        new_median = statistics.median(new_ms)
        ratio = old_median / new_median
        print("AABB_BOUNDS_PAIRED_CPU_EVIDENCE " + json.dumps({
            "python": sys.version.split()[0],
            "numpy": np.__version__, "seed": 1234,
            "repeats": 15, "inner_loops": 5000,
            "old_median_ms": round(old_median, 6),
            "new_median_ms": round(new_median, 6),
            "speedup": round(ratio, 4),
            "scope": "AABB bounds inline optimization",
        }, sort_keys=True))

        # Test gate for speedup
        self.assertGreaterEqual(ratio, 1.5, "AABB inline bounds optimization regressed")


if __name__ == "__main__":
    unittest.main()
