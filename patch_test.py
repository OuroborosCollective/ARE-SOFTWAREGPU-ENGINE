import math
import numpy as np
import time

s0 = [1.5, 2.5]
s1 = [3.5, 4.5]
s2 = [5.5, 6.5]
fb_w, y_start, y_end = 100, 0, 100

def original():
    for _ in range(10000):
        min_x = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
        max_x = min(fb_w - 1, int(np.ceil(max(s0[0], s1[0], s2[0]))))
        min_y = max(y_start, int(np.floor(min(s0[1], s1[1], s2[1]))))
        max_y = min(y_end - 1, int(np.ceil(max(s0[1], s1[1], s2[1]))))

def optimized():
    for _ in range(10000):
        min_x = max(0, int(math.floor(min(s0[0], s1[0], s2[0]))))
        max_x = min(fb_w - 1, int(math.ceil(max(s0[0], s1[0], s2[0]))))
        min_y = max(y_start, int(math.floor(min(s0[1], s1[1], s2[1]))))
        max_y = min(y_end - 1, int(math.ceil(max(s0[1], s1[1], s2[1]))))

def optimized2():
    for _ in range(10000):
        min_x = max(0, math.floor(min(s0[0], s1[0], s2[0])))
        max_x = min(fb_w - 1, math.ceil(max(s0[0], s1[0], s2[0])))
        min_y = max(y_start, math.floor(min(s0[1], s1[1], s2[1])))
        max_y = min(y_end - 1, math.ceil(max(s0[1], s1[1], s2[1])))

t0 = time.time()
original()
print("Original:", time.time() - t0)

t0 = time.time()
optimized()
print("Optimized with int():", time.time() - t0)

t0 = time.time()
optimized2()
print("Optimized without int():", time.time() - t0)
