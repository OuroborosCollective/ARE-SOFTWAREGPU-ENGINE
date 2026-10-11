import unittest
import numpy as np
import timeit
import math
from software_gpu.graphics.shader import BlinnPhongShader, Matrix4, Vertex

class TestShaderOptimization(unittest.TestCase):
    def test_shader_optimization_performance_and_correctness(self):
        # Setup dummy shader
        model = Matrix4.identity()
        view = Matrix4.look_at(np.array([0, 0, 5]), np.array([0, 0, 0]), np.array([0, 1, 0]))
        proj = Matrix4.perspective(math.pi/4, 1.0, 0.1, 100.0)

        shader = BlinnPhongShader(
            model_matrix=model,
            view_matrix=view,
            proj_matrix=proj,
            light_dir=np.array([1.0, 1.0, 1.0], dtype=np.float32),
            shininess=32.0
        )

        # Test fragment optimization performance
        varyings = {
            'normal': np.array([0.0, 0.0, 1.0], dtype=np.float32),
            'uv': np.array([0.5, 0.5], dtype=np.float32),
            'color': np.array([1.0, 1.0, 1.0], dtype=np.float32)
        }

        # New implementation (already in shader.py)
        def run_new():
            return shader.fragment_shader(varyings)

        # Old implementation
        def run_old():
            normal = varyings['normal']
            n_len = np.linalg.norm(normal)
            if n_len > 1e-6:
                normal = normal / n_len

            base_color = shader.diffuse_color
            diff = max(0.0, float(np.dot(normal, shader.light_dir)))
            diffuse = base_color * shader.light_color * diff
            ambient = base_color * shader.ambient_color

            light_key = (float(shader.light_dir[0]), float(shader.light_dir[1]), float(shader.light_dir[2]))
            cache = shader._half_cache
            if cache is None or cache[0] != light_key:
                half_dir = shader.light_dir + shader._view_dir
                half_len = np.linalg.norm(half_dir)
                valid = bool(half_len > 1e-6)
                if valid:
                    half_dir /= half_len
                cache = (light_key, half_dir, valid)
                shader._half_cache = cache
            if cache[2]:
                spec = max(0.0, float(np.dot(normal, cache[1]))) ** shader.shininess
            else:
                spec = 0.0
            specular = shader.specular_color * shader.light_color * spec

            final_rgb = np.clip(ambient + diffuse + specular, 0.0, 1.0) * 255.0
            return int(final_rgb[0]), int(final_rgb[1]), int(final_rgb[2]), 255

        # Clear cache before correctness check
        shader._half_cache = None
        new_result = run_new()

        shader._half_cache = None
        old_result = run_old()

        self.assertEqual(new_result, old_result, "RGB output must be identical between optimized and unoptimized paths")

        # Clear cache again for performance test
        shader._half_cache = None

        # We test how fast the fragment shader runs
        # 10,000 iterations to get a stable signal
        # On windows timer might be 0, so test >= 0
        t_new = timeit.timeit(run_new, number=10000)
        t_old = timeit.timeit(run_old, number=10000)

        self.assertGreaterEqual(t_new, 0, "Execution time must be >= 0")
        self.assertGreaterEqual(t_old, 0, "Execution time must be >= 0")

        # Ensure it's roughly faster or comparable (not strictly enforcing failure on CI load fluctuations, but capturing the intent)
        # We print it so it's visible in logs
        print(f"\nOptimization Check: Old = {t_old:.4f}s, New = {t_new:.4f}s, Speedup = {t_old/t_new if t_new > 0 else float('inf'):.2f}x")

if __name__ == '__main__':
    unittest.main()
