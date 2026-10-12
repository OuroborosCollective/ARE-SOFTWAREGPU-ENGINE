import numpy as np
from software_gpu.graphics.shader import BlinnPhongShader

class OptShader(BlinnPhongShader):
    def fragment_shader(self, varyings: dict):
        normal = varyings['normal']
        n_len = np.linalg.norm(normal)
        if n_len > 1e-6:
            normal = normal / n_len

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


rng = np.random.default_rng(20261011)
texture = rng.integers(0, 256, size=(16, 16, 3), dtype=np.uint8)
from software_gpu.graphics.shader import Vertex, Matrix4

vertices = [
    Vertex(np.array([-0.92, -0.87, 0.30]), normal=np.array([0.20, 0.30, 1.00]), uv=np.array([0.05, 0.91])),
    Vertex(np.array([ 0.90, -0.85, 0.30]), normal=np.array([1.00, 0.20, 0.15]), uv=np.array([0.90, 0.85])),
    Vertex(np.array([ 0.10,  0.94, 0.30]), normal=np.array([-0.2, 1.0, 0.5]), uv=np.array([0.50, 0.05])),
    Vertex(np.array([-0.68, -0.43, 0.15]), normal=np.array([0.4, -0.1, 1.0]), uv=np.array([0.05, 0.77])),
    Vertex(np.array([ 0.88, -0.14, 0.15]), normal=np.array([0.0, 0.3, 1.0]), uv=np.array([0.95, 0.13])),
    Vertex(np.array([-0.11,  0.70, 0.15]), normal=np.array([0.7, 0.6, 0.6]), uv=np.array([0.41, 0.35])),
]

def _pair(light=None, texture=None, shininess=32.0):
    if light is None:
        light = np.array([0.5, 0.8, 1.0], dtype=np.float32)
    params = dict(
        model_matrix=Matrix4.identity(), view_matrix=Matrix4.identity(),
        proj_matrix=Matrix4.identity(), light_dir=light.copy(),
        light_color=np.array([1.0, 1.0, 1.0], dtype=np.float32),
        ambient_color=np.array([0.2, 0.25, 0.35], dtype=np.float32),
        diffuse_color=np.array([0.2, 0.6, 0.9], dtype=np.float32),
        specular_color=np.array([1.0, 1.0, 1.0], dtype=np.float32),
        shininess=shininess, texture=texture)

    # We load the exact copy of BlinnPhongShader from software_gpu.graphics.shader as s1, and OptShader as s2.
    from software_gpu.tests.test_shader_half_vector_cache import BaselineShader
    return BaselineShader(**params), OptShader(**params)

faces = [(0, 1, 2), (3, 4, 5)]

s1, s2 = _pair(texture=texture)

from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.framebuffer import Framebuffer

fb1 = Framebuffer(80, 80)
fb1.clear(17, 19, 23, 255, depth=1.0)
renderer1 = SoftwareRasterizer(fb1, backend="tiles", num_threads=1, tile_size=16)
renderer1.draw_mesh(vertices, faces, s1)
renderer1.executor.shutdown(wait=True)

fb2 = Framebuffer(80, 80)
fb2.clear(17, 19, 23, 255, depth=1.0)
renderer2 = SoftwareRasterizer(fb2, backend="tiles", num_threads=1, tile_size=16)
renderer2.draw_mesh(vertices, faces, s2)
renderer2.executor.shutdown(wait=True)

c1 = fb1.color_buffer
c2 = fb2.color_buffer

diffs = np.where(c1 != c2)
for y, x, c in zip(diffs[0], diffs[1], diffs[2]):
    print(f"Diff at {x}, {y}, ch {c}: baseline {c1[y, x, c]} != opt {c2[y, x, c]}")

print(f"Total diffs: {len(diffs[0])}")
