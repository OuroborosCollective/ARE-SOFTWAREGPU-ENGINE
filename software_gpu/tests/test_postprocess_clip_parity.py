"""Independent, deterministic CPU-pixel and no-input-mutation regression for clip optimization."""
import unittest

import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.postprocess import FXAAPass, GamingPostProcessing, MSAAFramebuffer


class PostprocessClipParityTest(unittest.TestCase):
    def test_framebuffer_and_msaa_packed_color_uint8_inputs(self):
        rgba = tuple(np.uint8(v) for v in (7, 111, 203, 255))
        for framebuffer in (Framebuffer(13, 7), MSAAFramebuffer(13, 7, samples=4)):
            framebuffer.clear(*rgba, depth=0.375)
            pixels = (framebuffer.color_buffer if hasattr(framebuffer, "color_buffer")
                      else framebuffer.color_samples)
            self.assertTrue(np.all(pixels == np.asarray(rgba, dtype=np.uint8)))
            depth = (framebuffer.depth_buffer if hasattr(framebuffer, "depth_buffer")
                     else framebuffer.depth_samples)
            self.assertTrue(np.all(depth == np.float32(0.375)))

    def test_aces_optimized_output_exact_reference_and_no_input_mutation(self):
        rng = np.random.default_rng(20261104)
        for dtype in (np.float32, np.float64):
            value = rng.uniform(-1.5, 8.0, size=(13, 11, 3)).astype(dtype)
            before = value.copy()
            x = np.maximum(0.0, value)
            expected = np.clip((x * (2.51 * x + 0.03))
                               / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0)
            actual = GamingPostProcessing.aces_tone_mapping(value)
            np.testing.assert_array_equal(actual, expected)
            np.testing.assert_array_equal(value, before)

    def test_full_fxaa_and_bloom_repeat_exact_and_preserve_input(self):
        fb = Framebuffer(19, 17)
        h, w = np.indices((17, 19))
        fb.color_buffer[..., 0] = (w * 19 + h * 7) % 256
        fb.color_buffer[..., 1] = (w * 13 + h * 29) % 256
        fb.color_buffer[..., 2] = (w * 5 + h * 37) % 256
        fb.color_buffer[..., 3] = 255
        fb.depth_buffer[...] = np.float32(0.35)
        color_before = fb.color_buffer.copy()
        depth_before = fb.depth_buffer.copy()
        for render in (FXAAPass.apply, GamingPostProcessing.apply_bloom_and_hdr):
            first = render(fb)
            second = render(fb)
            np.testing.assert_array_equal(first.color_buffer, second.color_buffer)
            np.testing.assert_array_equal(first.depth_buffer, second.depth_buffer)
            np.testing.assert_array_equal(first.depth_buffer, depth_before)
            np.testing.assert_array_equal(fb.color_buffer, color_before)
            np.testing.assert_array_equal(fb.depth_buffer, depth_before)

    def test_aces_zero_dimensional_and_numpy_scalar_are_supported(self):
        for source in (np.array(0.5), np.float32(0.5), np.float64(0.5)):
            actual = GamingPostProcessing.aces_tone_mapping(source)
            x = np.maximum(0.0, source)
            expected = np.clip((x * (2.51 * x + 0.03)) /
                               (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0)
            np.testing.assert_equal(actual, expected)



import unittest
from unittest.mock import patch

class TestPostprocessMock(unittest.TestCase):
    @patch('numpy.floor')
    @patch('numpy.ceil')
    def test_msaa_rasterizer_bounds_optimization(self, mock_ceil, mock_floor):
        from software_gpu.graphics.postprocess import MSAAFramebuffer, MSAARasterizer
        from software_gpu.graphics.shader import Shader, Vertex

        fb = MSAAFramebuffer(64, 64)
        rast = MSAARasterizer(fb)

        class MockShader(Shader):
            def vertex_shader(self, v): return v.position, {}
            def fragment_shader(self, var): return 1.0, 1.0, 1.0, 1.0

        v1 = Vertex([10.0, 10.0, 0.5, 1.0])
        v2 = Vertex([50.0, 10.0, 0.5, 1.0])
        v3 = Vertex([30.0, 50.0, 0.5, 1.0])

        rast.draw_mesh([v1, v2, v3], [(0, 1, 2)], MockShader())

        mock_floor.assert_not_called()
        mock_ceil.assert_not_called()

if __name__ == "__main__":
    unittest.main()
