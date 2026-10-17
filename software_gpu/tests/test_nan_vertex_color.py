import unittest
import numpy as np
from software_gpu.graphics.batch_shader import VertexColorShader

class TestVertexColorShader(unittest.TestCase):
    def test_nan_color_raises_value_error(self):
        shader = VertexColorShader()
        with self.assertRaises(ValueError):
            shader.fragment_shader({"color": np.array([float('nan'), 0.5, 0.5])})
        with self.assertRaises(ValueError):
            shader.fragment_shader({"color": np.array([0.5, float('nan'), 0.5])})
        with self.assertRaises(ValueError):
            shader.fragment_shader({"color": np.array([0.5, 0.5, float('nan')])})

if __name__ == '__main__':
    unittest.main()
