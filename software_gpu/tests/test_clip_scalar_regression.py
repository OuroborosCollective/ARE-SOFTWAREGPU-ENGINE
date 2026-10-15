import unittest
import numpy as np
import math
from software_gpu.graphics.shader import BlinnPhongShader

class TestShaderScalarClip(unittest.TestCase):
    def test_shader_nan_handling(self):
        # Create dummy shader with valid properties
        shader = BlinnPhongShader(
            np.eye(4, dtype=np.float32),
            np.eye(4, dtype=np.float32),
            np.eye(4, dtype=np.float32)
        )
        # Override diffuse to be NaN
        shader.diffuse_color = np.array([float('nan'), 0.5, 0.5], dtype=np.float32)

        varyings = {
            'normal': np.array([0.0, 0.0, 1.0], dtype=np.float32),
            'uv': np.array([0.5, 0.5], dtype=np.float32),
            'color': np.array([1.0, 1.0, 1.0], dtype=np.float32),
        }

        with self.assertRaises(ValueError):
            shader.fragment_shader(varyings)

        # Test NaN on G
        shader.diffuse_color = np.array([0.5, float('nan'), 0.5], dtype=np.float32)
        with self.assertRaises(ValueError):
            shader.fragment_shader(varyings)

        # Test NaN on B
        shader.diffuse_color = np.array([0.5, 0.5, float('nan')], dtype=np.float32)
        with self.assertRaises(ValueError):
            shader.fragment_shader(varyings)

if __name__ == '__main__':
    unittest.main()
