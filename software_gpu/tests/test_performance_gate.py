import unittest
import time
import numpy as np
import statistics
from software_gpu.graphics.shader import BlinnPhongShader, Matrix4

class TestPerformanceGate(unittest.TestCase):
    def test_fragment_shader_scalar_optimization_speedup(self):
        """Regression test / Test Gate to ensure the scalar fragment_shader optimization maintains a speedup
        over the baseline numpy implementation.
        """
        # Baseline implementation (pre-optimization)
        def baseline_fragment_shader(self, varyings: dict) -> tuple:
            normal = varyings['normal']
            n_len = np.linalg.norm(normal)
            if n_len > 1e-6:
                normal = normal / n_len

            base_color = self.diffuse_color
            texture = self.texture
            if texture is not None:
                u, v = varyings['uv'][0], varyings['uv'][1]
                u = max(0.0, min(1.0, u))
                v = max(0.0, min(1.0, v))
                th, tw = texture.shape[0], texture.shape[1]
                tx = int(u * (tw - 1))
                ty = int(v * (th - 1))
                tex_sample = texture[ty, tx, :3] / 255.0
                base_color = tex_sample

            diff = max(0.0, float(np.dot(normal, self.light_dir)))
            diffuse = base_color * self.light_color * diff

            ambient = base_color * self.ambient_color

            light_key = (float(self.light_dir[0]), float(self.light_dir[1]),
                         float(self.light_dir[2]))
            cache = self._half_cache
            if cache is None or cache[0] != light_key:
                half_dir = self.light_dir + self._view_dir
                half_len = np.linalg.norm(half_dir)
                valid = bool(half_len > 1e-6)
                if valid:
                    half_dir /= half_len
                cache = (light_key, half_dir, valid)
                self._half_cache = cache

            if cache[2]:
                spec = max(0.0, float(np.dot(normal, cache[1]))) ** self.shininess
            else:
                spec = 0.0

            specular = self.specular_color * self.light_color * spec

            final_rgb = np.clip(ambient + diffuse + specular, 0.0, 1.0) * 255.0
            return int(final_rgb[0]), int(final_rgb[1]), int(final_rgb[2]), 255


        model = Matrix4.identity()
        shader1 = BlinnPhongShader(model, model, model)
        shader2 = BlinnPhongShader(model, model, model)

        # Override shader1 to use the unoptimized baseline logic
        shader1.fragment_shader = baseline_fragment_shader.__get__(shader1, BlinnPhongShader)

        rng = np.random.default_rng(42)
        normals = [rng.normal(size=3).astype(np.float32) for _ in range(50000)]
        varyings_list = [{"normal": n, "uv": np.array([0.5, 0.5], dtype=np.float32)} for n in normals]

        # Warmup
        for v in varyings_list[:1000]:
            shader1.fragment_shader(v)
            shader2.fragment_shader(v)

        t0 = time.perf_counter()
        for v in varyings_list:
            shader1.fragment_shader(v)
        t_baseline = time.perf_counter() - t0

        t0 = time.perf_counter()
        for v in varyings_list:
            shader2.fragment_shader(v)
        t_optimized = time.perf_counter() - t0

        speedup = t_baseline / max(t_optimized, 1e-9)
        print(f"\nBaseline time: {t_baseline:.4f}s, Optimized time: {t_optimized:.4f}s. Speedup: {speedup:.2f}x")

        # Ensure at least a 10% speedup
        self.assertGreater(speedup, 1.10, "Optimized scalar fragment shader did not provide the expected performance speedup.")

if __name__ == '__main__':
    unittest.main()
