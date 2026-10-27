import time
import unittest
import numpy as np
from software_gpu.graphics.geometry import _distance
from software_gpu.graphics.shader import BlinnPhongShader, Matrix4

class GeometryOptPerformanceGate(unittest.TestCase):
    def test_distance_optimization_speedup_is_significant(self):
        """
        Verify that direct indexing in _distance provides a meaningful speedup
        over tuple unpacking, preventing future performance regressions.
        """
        def _distance_unoptimized(position: np.ndarray, plane: int) -> float:
            x, y, z, w = position
            if plane == 0: return w + x
            if plane == 1: return w - x
            if plane == 2: return w + y
            if plane == 3: return w - y
            if plane == 4: return w + z
            if plane == 5: return w - z
            return w - 1.0e-7

        p = np.array([1.0, 2.0, 3.0, 4.0])

        # Warmup
        for _ in range(100):
            _distance_unoptimized(p, 0)
            _distance(p, 0)

        iterations = 100000

        t0 = time.time()
        for _ in range(iterations):
            _distance_unoptimized(p, 0)
            _distance_unoptimized(p, 1)
            _distance_unoptimized(p, 2)
            _distance_unoptimized(p, 3)
            _distance_unoptimized(p, 4)
            _distance_unoptimized(p, 5)
        t_unopt = time.time() - t0

        t0 = time.time()
        for _ in range(iterations):
            _distance(p, 0)
            _distance(p, 1)
            _distance(p, 2)
            _distance(p, 3)
            _distance(p, 4)
            _distance(p, 5)
        t_opt = time.time() - t0

        self.assertTrue(t_unopt > t_opt, "Unoptimized version should be slower.")
        speedup = t_unopt / t_opt if t_opt > 0 else 0
        self.assertGreater(speedup, 1.2, f"Speedup ({speedup:.2f}x) is less than expected 1.2x. Regression detected.")

class ShaderOptPerformanceGate(unittest.TestCase):
    def test_ternary_clamp_optimization_speedup(self):
        """
        Verify that the actual fragment shader runs faster with the inline ternary clamp optimization.
        """
        shader = BlinnPhongShader(
            model_matrix=Matrix4.identity(),
            view_matrix=Matrix4.identity(),
            proj_matrix=Matrix4.identity(),
            light_dir=np.array([0.5, 0.8, 1.0], dtype=np.float32),
            light_color=np.array([1.0, 1.0, 1.0], dtype=np.float32),
            ambient_color=np.array([0.2, 0.25, 0.35], dtype=np.float32),
            diffuse_color=np.array([0.2, 0.6, 0.9], dtype=np.float32),
            specular_color=np.array([1.0, 1.0, 1.0], dtype=np.float32),
            shininess=32.0
        )

        varying = {
            'normal': np.array([0.0, 0.0, 1.0], dtype=np.float32),
            'uv': np.array([0.5, 0.5], dtype=np.float32),
            'color': np.array([1.0, 1.0, 1.0], dtype=np.float32)
        }

        def shader_unoptimized(shader, varyings):
            normal = varyings['normal']
            import math
            n_len = math.sqrt(normal[0]*normal[0] + normal[1]*normal[1] + normal[2]*normal[2])
            if n_len > 1e-6: normal = normal / n_len

            base_color = shader.diffuse_color

            diff = max(0.0, float(normal[0]*shader.light_dir[0] + normal[1]*shader.light_dir[1] + normal[2]*shader.light_dir[2]))
            diffuse = base_color * shader.light_color * diff

            ambient = base_color * shader.ambient_color

            light_key = (float(shader.light_dir[0]), float(shader.light_dir[1]), float(shader.light_dir[2]))
            cache = shader._half_cache
            if cache is None or cache[0] != light_key:
                half_dir = shader.light_dir + shader._view_dir
                half_len = np.linalg.norm(half_dir)
                valid = bool(half_len > 1e-6)
                if valid: half_dir /= half_len
                cache = (light_key, half_dir, valid)
                shader._half_cache = cache
            if cache[2]:
                spec = max(0.0, float(normal[0]*cache[1][0] + normal[1]*cache[1][1] + normal[2]*cache[1][2])) ** shader.shininess
            else:
                spec = 0.0
            specular = shader.specular_color * shader.light_color * spec

            r = float(ambient[0] + diffuse[0] + specular[0])
            g = float(ambient[1] + diffuse[1] + specular[1])
            b = float(ambient[2] + diffuse[2] + specular[2])

            if r != r or g != g or b != b:
                raise ValueError("cannot convert float NaN to integer")

            return (
                int((r if r < 1.0 else 1.0) * 255.0) if r > 0.0 else 0,
                int((g if g < 1.0 else 1.0) * 255.0) if g > 0.0 else 0,
                int((b if b < 1.0 else 1.0) * 255.0) if b > 0.0 else 0,
                255
            )

        iterations = 50000

        # Warmup
        for _ in range(100):
            shader_unoptimized(shader, varying)
            shader.fragment_shader(varying)

        t0 = time.time()
        for _ in range(iterations):
            shader_unoptimized(shader, varying)
        t_unopt = time.time() - t0

        t0 = time.time()
        for _ in range(iterations):
            shader.fragment_shader(varying)
        t_opt = time.time() - t0

        self.assertTrue(t_unopt > t_opt, "Unoptimized version should be slower.")
        speedup = t_unopt / t_opt if t_opt > 0 else 0
        self.assertGreater(speedup, 1.05, f"Ternary speedup ({speedup:.2f}x) is less than expected 1.05x. Regression detected.")

if __name__ == "__main__":
    unittest.main()
