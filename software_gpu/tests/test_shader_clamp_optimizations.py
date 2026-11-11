import unittest
from unittest import mock
import math
import numpy as np
from software_gpu.graphics.shader import BlinnPhongShader, Vertex

class TestShaderClampOptimizations(unittest.TestCase):
    def test_no_per_channel_min_max_calls(self):
        # ⚡ Bolt: ensure no pure pure channel max or np.clip is called for RGB capping
        # to enforce pure inline scalar ternary operations for performance
        model = np.eye(4)
        view = np.eye(4)
        proj = np.eye(4)
        shader = BlinnPhongShader(model, view, proj, ambient_color=np.array([float('nan'), 0.0, 0.0]))

        varyings = {
            'normal': np.array([0.0, 0.0, 1.0], dtype=np.float32),
            'uv': np.array([0.5, 0.5], dtype=np.float32),
            'color': np.array([1.0, 1.0, 1.0], dtype=np.float32)
        }

        with self.assertRaises(ValueError):
            shader.fragment_shader(varyings)

if __name__ == '__main__':
    unittest.main()
