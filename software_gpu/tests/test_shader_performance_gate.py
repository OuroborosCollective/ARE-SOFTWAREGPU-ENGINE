import unittest
import time
import numpy as np
from software_gpu.graphics.shader import BlinnPhongShader, Matrix4

class TestShaderOptimizationGate(unittest.TestCase):
    def test_inline_ternary_performance_gate(self):
        shader = BlinnPhongShader(Matrix4.identity(), Matrix4.identity(), Matrix4.identity())

        normals = [np.array([0.0, 0.0, 1.0], dtype=np.float32) for _ in range(5000)]
        uv = np.array([0.5, 0.5], dtype=np.float32)

        start = time.perf_counter()
        for n in normals:
            shader.fragment_shader({"normal": n, "uv": uv})
        elapsed = time.perf_counter() - start

        # Test gate allowing up to 0.5 seconds for execution
        self.assertLess(elapsed, 0.5, "Fragment shader optimization gate failed (too slow).")

if __name__ == "__main__":
    unittest.main()
