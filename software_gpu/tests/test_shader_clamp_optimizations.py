"""Real Blinn-Phong RGBA semantics before/after inlining scalar clamp.

CPU-only exact-output tests. Microbenchmark results are separately measured
with actual renderer invocations; no timing literals are used as evidence.
"""
import math
import unittest

import numpy as np

from software_gpu.graphics.shader import BlinnPhongShader, Matrix4


def reference_byte(value):
    if math.isnan(value):
        raise ValueError("cannot convert float NaN to integer")
    return int(min(1.0, max(0.0, value)) * 255.0)


def ambient_only(colors, ambient=(1.0, 1.0, 1.0)):
    # Use actual full lighting shader. Light energy = 0; all pixel channels
    # derive from the ambient term, with identical numpy float32 arithmetic.
    return BlinnPhongShader(
        model_matrix=Matrix4.identity(),
        view_matrix=Matrix4.identity(),
        proj_matrix=Matrix4.identity(),
        light_dir=np.array([0, 0, 1], dtype=np.float32),
        light_color=np.zeros(3, dtype=np.float32),
        diffuse_color=np.asarray(colors, dtype=np.float32),
        ambient_color=np.asarray(ambient, dtype=np.float32),
        specular_color=np.zeros(3, dtype=np.float32),
    )


class BlinnPhongScalarClipParity(unittest.TestCase):
    def test_finite_channels_against_existing_scalar_contract(self):
        candidates=(-3.0, -0.0, 0.0, 0.000001, 0.2, 0.5, 0.75,
                    0.99999994, 1.0, 1.0000001, 2.0)
        varying={"normal":np.array([0, 0, 1], dtype=np.float32),
                 "uv":np.array([0.5, 0.5], dtype=np.float32)}
        for color in candidates:
            shader=ambient_only((color, color / 2, -color))
            with self.subTest(color=color):
                actual=shader.fragment_shader(varying)
                triple=np.asarray((color, color / 2, -color), dtype=np.float32)
                expected=tuple(reference_byte(float(v)) for v in triple)+(255,)
                self.assertEqual(actual, expected)

    def test_nan_in_each_channel_keeps_explicit_value_error(self):
        varying={"normal":np.array([0, 0, 1], dtype=np.float32),
                 "uv":np.array([0.5, 0.5], dtype=np.float32)}
        for index in range(3):
            color=[0.3, 0.5, 0.7]
            color[index]=float("nan")
            shader=ambient_only(color)
            with self.subTest(channel=index):
                with self.assertRaisesRegex(ValueError, "cannot convert float NaN"):
                    shader.fragment_shader(varying)

    def test_infinite_ambient_channels_saturate_without_swallowing_nan(self):
        varying={"normal":np.array([0, 0, 1], dtype=np.float32),
                 "uv":np.array([0.5, 0.5], dtype=np.float32)}
        shader=ambient_only((1.0, 1.0, 0.5), (float("inf"), -float("inf"), 1.0))
        self.assertEqual(shader.fragment_shader(varying), (255, 0, 127, 255))


if __name__ == "__main__":
    unittest.main()
