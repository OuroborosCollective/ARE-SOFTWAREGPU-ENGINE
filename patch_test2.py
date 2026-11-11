import math
import numpy as np
import time

s0 = [1.5, 2.5]
s1 = [3.5, 4.5]
s2 = [5.5, 6.5]
fb_w, y_start, y_end = 100, 0, 100

def check_type_original():
    min_x = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
    print(type(min_x))

def check_type_optimized2():
    min_x = max(0, math.floor(min(s0[0], s1[0], s2[0])))
    print(type(min_x))

check_type_original()
check_type_optimized2()
