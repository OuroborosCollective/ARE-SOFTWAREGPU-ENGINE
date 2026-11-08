import unittest
import time
import numpy as np
from software_gpu.graphics.shader import BlinnPhongShader

class TestShaderPerformance(unittest.TestCase):
    def test_fragment_shader_performance(self):
        # Create a shader with typical settings
        model_matrix = np.eye(4, dtype=np.float32)
        view_matrix = np.eye(4, dtype=np.float32)
        proj_matrix = np.eye(4, dtype=np.float32)

        shader = BlinnPhongShader(
            model_matrix=model_matrix,
            view_matrix=view_matrix,
            proj_matrix=proj_matrix,
        )

        # Prepare sample varyings
        varyings = {
            'normal': np.array([0.5, 0.5, 0.707], dtype=np.float32),
            'uv': np.array([0.5, 0.5], dtype=np.float32),
            'color': np.array([1.0, 1.0, 1.0], dtype=np.float32),
        }

        # Run warmup
        for _ in range(100):
            shader.fragment_shader(varyings)

        # Measure performance
        num_iterations = 100000
        start_time = time.perf_counter()
        for _ in range(num_iterations):
            shader.fragment_shader(varyings)
        elapsed_time = time.perf_counter() - start_time

        # Assert the time is less than a generous threshold
        # to ensure future optimizations aren't completely lost.
        # Note: generous threshold is used to prevent test flakiness in slower CI environments
        self.assertLess(elapsed_time, 15.0)

if __name__ == '__main__':
    unittest.main()
