"""PR sweep: independent hot-path behavior oracle, never performance evidence."""
import unittest
import numpy as np

from software_gpu.graphics.geometry import is_top_left
from software_gpu.graphics.shader import BlinnPhongShader, Matrix4


class TestConsolidatedHotpathParity(unittest.TestCase):
    def test_top_left_matches_previous_predicate_across_nonfinite_edges(self):
        vals = (np.float32(-np.inf), np.float32(-1), np.float32(-0.0),
                np.float32(0.0), np.float32(1), np.float32(np.inf), np.float32(np.nan))
        for dtype in (np.float32, np.float64):
            for ay in vals:
                for by in vals:
                    for ax, bx in ((0.0, 1.0), (1.0, 0.0), (float("nan"), 0.0)):
                        a = np.array([ax, ay], dtype=dtype)
                        b = np.array([bx, by], dtype=dtype)
                        dy = float(b[1] - a[1])
                        dx = float(b[0] - a[0])
                        expected = dy > 0.0 or (dy == 0.0 and dx < 0.0)
                        with self.subTest(dtype=str(dtype), a=a.tolist(), b=b.tolist()):
                            self.assertEqual(is_top_left(a, b), expected)

    def test_uv_clamping_matches_builtin_on_real_fragment_shader(self):
        texture = np.array([
            [[255, 0, 0], [0, 255, 0], [0, 0, 255]],
            [[0, 255, 255], [255, 0, 255], [255, 255, 0]],
        ], dtype=np.uint8)
        shader = BlinnPhongShader(
            model_matrix=Matrix4.identity(), view_matrix=Matrix4.identity(),
            proj_matrix=Matrix4.identity(), texture=texture,
            ambient_color=np.ones(3, dtype=np.float32),
            light_color=np.zeros(3, dtype=np.float32),
            specular_color=np.zeros(3, dtype=np.float32),
        )
        normal = np.array([0, 0, 1], dtype=np.float32)
        coords = [np.float32(-np.inf), np.float32(-2.0), np.float32(-0.0),
                  np.float32(0), np.float32(.1), np.float32(.5),
                  np.float32(1), np.float32(2), np.float32(np.inf),
                  np.float32(np.nan)]
        for u in coords:
            for v in coords:
                with self.subTest(u=str(u), v=str(v)):
                    original = shader.fragment_shader({"normal": normal, "uv": np.array([u, v], dtype=np.float32)})
                    expected_u = max(0.0, min(1.0, u))
                    expected_v = max(0.0, min(1.0, v))
                    reference = shader.fragment_shader({
                        "normal": normal,
                        "uv": np.array([expected_u, expected_v], dtype=np.float32),
                    })
                    self.assertEqual(original, reference)


if __name__ == "__main__":
    unittest.main()
