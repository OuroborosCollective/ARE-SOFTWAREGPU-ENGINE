import math
import numpy as np
import time

def test_math_ceil_floor():
    s0 = [1.5, 2.5]
    s1 = [3.5, 4.5]
    s2 = [5.5, 6.5]
    frame_w = 100
    frame_h = 100

    # Original
    x0_orig = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
    x1_orig = min(frame_w - 1, int(np.ceil(max(s0[0], s1[0], s2[0]))))

    # Optimized
    x0_opt = max(0, int(math.floor(min(s0[0], s1[0], s2[0]))))
    x1_opt = min(frame_w - 1, int(math.ceil(max(s0[0], s1[0], s2[0]))))

    print(f"{x0_orig=} {x0_opt=}")
    print(f"{x1_orig=} {x1_opt=}")

test_math_ceil_floor()
