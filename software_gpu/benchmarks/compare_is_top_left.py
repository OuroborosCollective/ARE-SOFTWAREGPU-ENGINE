import timeit
import numpy as np

def run_benchmark():
    setup = """
import numpy as np
a = np.array([0.0, 0.0])
b = np.array([1.0, 1.0])

def is_top_left_original(a, b):
    dy, dx = float(b[1] - a[1]), float(b[0] - a[0])
    return dy > 0.0 or (dy == 0.0 and dx < 0.0)

def is_top_left_optimized(a, b):
    dy = b[1] - a[1]
    if dy > 0: return True
    if dy < 0: return False
    return b[0] < a[0]
"""

    original = timeit.timeit("is_top_left_original(a, b)", setup=setup, number=1000000)
    optimized = timeit.timeit("is_top_left_optimized(a, b)", setup=setup, number=1000000)

    print(f"Original: {original:.4f}s")
    print(f"Optimized: {optimized:.4f}s")
    print(f"Speedup: {original/optimized:.2f}x")

if __name__ == "__main__":
    run_benchmark()
