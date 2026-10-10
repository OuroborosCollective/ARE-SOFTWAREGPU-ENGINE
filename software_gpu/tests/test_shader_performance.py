import unittest
import numpy as np

from software_gpu.graphics.shader import BlinnPhongShader, Matrix4

class OriginalBlinnPhongShader:
    """The original unoptimized Blinn-Phong lighting shader (Ambient + Diffuse + Specular) for regression testing."""
    def __init__(
        self,
        model_matrix: np.ndarray,
        view_matrix: np.ndarray,
        proj_matrix: np.ndarray,
        light_dir: np.ndarray = np.array([0.5, 0.8, 1.0], dtype=np.float32),
        light_color: np.ndarray = np.array([1.0, 1.0, 1.0], dtype=np.float32),
        ambient_color: np.ndarray = np.array([0.2, 0.25, 0.35], dtype=np.float32),
        diffuse_color: np.ndarray = np.array([0.2, 0.6, 0.9], dtype=np.float32),
        specular_color: np.ndarray = np.array([1.0, 1.0, 1.0], dtype=np.float32),
        shininess: float = 32.0,
        texture: np.ndarray = None
    ):
        self.mvp = proj_matrix @ view_matrix @ model_matrix
        self.model = model_matrix
        self.normal_matrix = np.linalg.inv(model_matrix[:3, :3]).T

        self.light_dir = light_dir / np.linalg.norm(light_dir)
        self.light_color = light_color
        self.ambient_color = ambient_color
        self.diffuse_color = diffuse_color
        self.specular_color = specular_color
        self.shininess = shininess
        self.texture = texture

    def fragment_shader(self, varyings: dict) -> tuple:
        normal = varyings['normal']
        n_len = np.linalg.norm(normal)
        if n_len > 1e-6:
            normal = normal / n_len

        # Base surface color (either from texture or vertex/material diffuse)
        base_color = self.diffuse_color
        if self.texture is not None:
            u, v = varyings['uv'][0], varyings['uv'][1]
            u = max(0.0, min(1.0, u))
            v = max(0.0, min(1.0, v))
            th, tw = self.texture.shape[0], self.texture.shape[1]
            tx = int(u * (tw - 1))
            ty = int(v * (th - 1))
            tex_sample = self.texture[ty, tx, :3] / 255.0
            base_color = tex_sample

        # Diffuse component (Lambertian)
        diff = max(0.0, float(np.dot(normal, self.light_dir)))
        diffuse = base_color * self.light_color * diff

        # Ambient component
        ambient = base_color * self.ambient_color

        # Specular component (Blinn-Phong halfway vector)
        view_dir = np.array([0.0, 0.0, 1.0], dtype=np.float32)  # In camera space looking towards +z
        half_dir = (self.light_dir + view_dir)
        half_len = np.linalg.norm(half_dir)
        if half_len > 1e-6:
            half_dir /= half_len
            spec = max(0.0, float(np.dot(normal, half_dir))) ** self.shininess
        else:
            spec = 0.0
        specular = self.specular_color * self.light_color * spec

        final_rgb = np.clip(ambient + diffuse + specular, 0.0, 1.0) * 255.0
        return int(final_rgb[0]), int(final_rgb[1]), int(final_rgb[2]), 255


class TestShaderPerformanceOptimization(unittest.TestCase):
    def setUp(self):
        self.model = Matrix4.identity()
        self.view = Matrix4.identity()
        self.proj = Matrix4.identity()
        self.texture = np.zeros((16, 16, 3), dtype=np.uint8)
        self.texture[8, 8, :] = [255, 128, 64] # random color

    def test_optimized_fragment_shader_matches_original(self):
        orig_shader = OriginalBlinnPhongShader(self.model, self.view, self.proj)
        opt_shader = BlinnPhongShader(self.model, self.view, self.proj)

        test_normals = [
            np.array([1.0, 0.0, 0.0], dtype=np.float32),
            np.array([0.0, 1.0, 0.0], dtype=np.float32),
            np.array([0.0, 0.0, 1.0], dtype=np.float32),
            np.array([0.5, 0.5, 0.5], dtype=np.float32),
            np.array([-0.5, -0.5, -0.5], dtype=np.float32),
            np.array([0.1, 0.9, -0.2], dtype=np.float32),
        ]

        for normal in test_normals:
            varyings = {'normal': normal, 'uv': np.array([0.0, 0.0], dtype=np.float32)}
            orig_result = orig_shader.fragment_shader(varyings)
            opt_result = opt_shader.fragment_shader(varyings)
            self.assertEqual(orig_result, opt_result, f"Failed on normal {normal}")

    def test_optimized_fragment_shader_matches_original_with_texture(self):
        orig_shader = OriginalBlinnPhongShader(self.model, self.view, self.proj, texture=self.texture)
        opt_shader = BlinnPhongShader(self.model, self.view, self.proj, texture=self.texture)

        varyings = {
            'normal': np.array([0.5, 0.5, 0.5], dtype=np.float32),
            'uv': np.array([0.5, 0.5], dtype=np.float32) # map to center of texture
        }
        orig_result = orig_shader.fragment_shader(varyings)
        opt_result = opt_shader.fragment_shader(varyings)

        self.assertEqual(orig_result, opt_result)
