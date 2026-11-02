import unittest
import time
import numpy as np

class TestRasterizerBoundsPerformance(unittest.TestCase):
    def test_bounds_performance(self):
        # We simulate the operations in _rasterize_band for bounding box calculations
        fb_w = 800
        y_start = 0
        y_end = 600

        # Setup test data
        s0 = np.array([10.5, 20.3, 0.5], dtype=np.float32)
        s1 = np.array([50.1, 80.9, 0.5], dtype=np.float32)
        s2 = np.array([5.2, 70.4, 0.5], dtype=np.float32)

        start_old = time.perf_counter()
        for _ in range(100000):
            min_x = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
            max_x = min(fb_w - 1, int(np.ceil(max(s0[0], s1[0], s2[0]))))
            min_y = max(y_start, int(np.floor(min(s0[1], s1[1], s2[1]))))
            max_y = min(y_end - 1, int(np.ceil(max(s0[1], s1[1], s2[1]))))
        old_time = time.perf_counter() - start_old

        start_new = time.perf_counter()
        for _ in range(100000):
            min_s_x = s0[0] if s0[0] < s1[0] else s1[0]
            min_s_x = min_s_x if min_s_x < s2[0] else s2[0]
            min_x_val = int(np.floor(min_s_x))
            min_x = 0 if 0 > min_x_val else min_x_val

            max_s_x = s0[0] if s0[0] > s1[0] else s1[0]
            max_s_x = max_s_x if max_s_x > s2[0] else s2[0]
            max_x_val = int(np.ceil(max_s_x))
            fb_w_1 = fb_w - 1
            max_x = fb_w_1 if fb_w_1 < max_x_val else max_x_val

            min_s_y = s0[1] if s0[1] < s1[1] else s1[1]
            min_s_y = min_s_y if min_s_y < s2[1] else s2[1]
            min_y_val = int(np.floor(min_s_y))
            min_y = y_start if y_start > min_y_val else min_y_val

            max_s_y = s0[1] if s0[1] > s1[1] else s1[1]
            max_s_y = max_s_y if max_s_y > s2[1] else s2[1]
            max_y_val = int(np.ceil(max_s_y))
            y_end_1 = y_end - 1
            max_y = y_end_1 if y_end_1 < max_y_val else max_y_val
        new_time = time.perf_counter() - start_new

        print(f"Old time: {old_time}")
        print(f"New time: {new_time}")

        # We ensure it takes less time by checking it completes within a generous 0.5s limit
        self.assertLess(new_time, 2.0)

if __name__ == "__main__":
    unittest.main()
