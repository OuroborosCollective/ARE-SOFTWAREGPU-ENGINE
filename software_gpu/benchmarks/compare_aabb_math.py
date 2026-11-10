import time
import numpy as np
import math

s0 = [1.2, 3.4, 5.6]
s1 = [2.3, 1.2, 7.8]
s2 = [0.1, 4.5, 6.7]
fb_w = 800

def orig():
    return max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))

def opt():
    m_x0 = s1[0] if s1[0] < s2[0] else s2[0]
    m_min_x = math.floor(s0[0] if s0[0] < m_x0 else m_x0)
    return m_min_x if m_min_x > 0 else 0

t0 = time.time()
for _ in range(1000000):
    orig()
orig_time = time.time() - t0

t0 = time.time()
for _ in range(1000000):
    opt()
opt_time = time.time() - t0

print(f"Original: {orig_time:.4f} s")
print(f"Optimized: {opt_time:.4f} s")
print(f"Speedup: {orig_time/opt_time:.2f}x")
