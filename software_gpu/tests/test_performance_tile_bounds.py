"""Deterministic tile bounds equivalence and paired CPU timing evidence.

This tests the inline ternary operator optimization for tile bounds calculation.
"""
import json
import statistics
import sys
import time
import unittest
import numpy as np

def _baseline_bounds(x0, x1, y0, y1, tile_x0, tile_x1, tile_y0, tile_y1):
    left, right = max(x0, tile_x0), min(x1, tile_x1)
    top, bottom = max(y0, tile_y0), min(y1, tile_y1)
    return left, right, top, bottom

def _optimized_bounds(x0, x1, y0, y1, tile_x0, tile_x1, tile_y0, tile_y1):
    left = x0 if x0 > tile_x0 else tile_x0
    right = x1 if x1 < tile_x1 else tile_x1
    top = y0 if y0 > tile_y0 else tile_y0
    bottom = y1 if y1 < tile_y1 else tile_y1
    return left, right, top, bottom


class TestTileBoundsPerformance(unittest.TestCase):
    def test_equivalent_scalar_and_inline_bounds(self):
        rng = np.random.default_rng(1234)
        for _ in range(100):
            x0 = rng.integers(-10, 100)
            x1 = x0 + rng.integers(1, 50)
            y0 = rng.integers(-10, 100)
            y1 = y0 + rng.integers(1, 50)
            tile_x0 = rng.integers(0, 50)
            tile_x1 = tile_x0 + 16
            tile_y0 = rng.integers(0, 50)
            tile_y1 = tile_y0 + 16

            baseline = _baseline_bounds(x0, x1, y0, y1, tile_x0, tile_x1, tile_y0, tile_y1)
            optimized = _optimized_bounds(x0, x1, y0, y1, tile_x0, tile_x1, tile_y0, tile_y1)

            self.assertEqual(baseline, optimized)

    def test_paired_bounds_timing_guard(self):
        rng = np.random.default_rng(1234)

        # Pre-generate inputs
        inputs = []
        for _ in range(1000):
            x0 = rng.integers(-10, 100)
            x1 = x0 + rng.integers(1, 50)
            y0 = rng.integers(-10, 100)
            y1 = y0 + rng.integers(1, 50)
            tile_x0 = rng.integers(0, 50)
            tile_x1 = tile_x0 + 16
            tile_y0 = rng.integers(0, 50)
            tile_y1 = tile_y0 + 16
            inputs.append((x0, x1, y0, y1, tile_x0, tile_x1, tile_y0, tile_y1))

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
        print("TILE_BOUNDS_PAIRED_CPU_EVIDENCE " + json.dumps({
            "python": sys.version.split()[0],
            "numpy": np.__version__, "seed": 1234,
            "repeats": 15, "inner_loops": 5000,
            "old_median_ms": round(old_median, 6),
            "new_median_ms": round(new_median, 6),
            "speedup": round(ratio, 4),
            "scope": "Tile bounds inline optimization",
        }, sort_keys=True))

        # Test gate for speedup
        self.assertGreaterEqual(ratio, 2.0, "Tile inline bounds optimization regressed")


if __name__ == "__main__":
    unittest.main()
