import unittest
import numpy as np
import time
from software_gpu.graphics.batch_shader import VertexColorShader

class TestPerformanceRegression(unittest.TestCase):
    def test_performance_regression_batch_shader(self):
        shader = VertexColorShader()

        # Test baseline performance
        varyings = {"color": np.array([0.5, 0.2, 0.8])}
        start = time.time()
        for _ in range(1000):
            shader.fragment_shader(varyings)
        end = time.time()

        self.assertLess(end - start, 0.05, "Performance of pure scalar loop is severely degraded, taking more than 50ms for 1000 iterations.")

    def test_byte_parity_no_regression(self):
        shader = VertexColorShader()
        np.random.seed(42)

        for _ in range(100):
            val = np.random.uniform(-1, 2, 3)
            varyings = {"color": val}

            # Simulated np.clip
            expected_rgb = np.clip(val * 255, 0, 255).astype(np.uint8)
            expected = (int(expected_rgb[0]), int(expected_rgb[1]), int(expected_rgb[2]), 255)

            # Run optimized shader
            actual = shader.fragment_shader(varyings)
            self.assertEqual(actual, expected)

    def test_nan_values_raise_exception(self):
        shader = VertexColorShader()
        for c in [[np.nan, 0, 0], [0, np.nan, 0], [0, 0, np.nan], [np.nan, np.nan, np.nan]]:
            varyings = {"color": np.array(c)}
            with self.assertRaises(ValueError):
                shader.fragment_shader(varyings)

if __name__ == '__main__':
    unittest.main()
