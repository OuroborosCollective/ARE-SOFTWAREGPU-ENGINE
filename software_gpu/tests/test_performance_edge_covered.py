"""Deterministic top-left equivalence and paired CPU timing evidence for PR #23.

Array timing is a microbenchmark, not a full-renderer throughput guarantee.
"""
import json
import statistics
import sys
import time
import unittest
import numpy as np

from software_gpu.graphics.geometry import edge_covered, is_top_left


def _baseline(value, a, b):
    return (value > 0) | ((value == 0) & is_top_left(a, b))


class TestEdgeCoveredPerformance(unittest.TestCase):
    def test_equivalent_scalar_and_array_edge_decisions(self):
        rng = np.random.default_rng(1234)
        arrays = (
            np.array([-np.inf, -4.0, -0.0, 0.0, 1e-10, 3.0, np.inf, np.nan], dtype=np.float32),
            np.array([-3, -1, 0, 1, 6], dtype=np.int32),
            rng.normal(size=(256, 256)).astype(np.float32),
            rng.normal(size=(256, 256)).astype(np.float64),
            0.0, -0.0, 1.0, float("nan"),
        )
        edges = (
            ([0.0, 0.0], [0.0, 1.0]),
            ([1.0, 0.0], [0.0, 0.0]),
            ([0.0, 1.0], [0.0, 0.0]),
            ([0.0, 0.0], [1.0, 0.0]),
        )
        for aa, bb in edges:
            a, b = np.asarray(aa, dtype=np.float32), np.asarray(bb, dtype=np.float32)
            for value in arrays:
                with self.subTest(edge=(aa, bb), value_type=str(type(value))):
                    np.testing.assert_array_equal(edge_covered(value, a, b), _baseline(value, a, b))

    def test_paired_array_timing_guard(self):
        rng = np.random.default_rng(1234)
        values = rng.normal(size=(1000, 1000)).astype(np.float64)
        a, b = np.array([0.0, 0.0]), np.array([1.0, 1.0])
        old_ms, new_ms = [], []
        for repetition in range(15):
            order = ((_baseline, old_ms), (edge_covered, new_ms))
            if repetition % 2:
                order = tuple(reversed(order))
            for fn, samples in order:
                start = time.perf_counter_ns()
                for _ in range(40):
                    last = fn(values, a, b)
                samples.append((time.perf_counter_ns() - start) / 1e6)
                self.assertEqual(last.shape, values.shape)
        old_median = statistics.median(old_ms)
        new_median = statistics.median(new_ms)
        ratio = old_median / new_median
        print("EDGE_COVERED_PAIRED_CPU_EVIDENCE " + json.dumps({
            "python": sys.version.split()[0],
            "numpy": np.__version__, "seed": 1234, "shape": [1000, 1000],
            "repeats": 15, "inner_loops": 40,
            "old_median_ms": round(old_median, 6),
            "new_median_ms": round(new_median, 6),
            "speedup": round(ratio, 4),
            "scope": "array edge predicate only",
        }, sort_keys=True))
        self.assertGreaterEqual(ratio, 1.05, "array edge predicate performance regressed")


if __name__ == "__main__":
    unittest.main()
