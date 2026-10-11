"""Pinned baseline differential tests for half-vector caching.

The BaselineShader.fragment_shader method is copied verbatim from main
85058622f7389af5cdb746d38e6cbfab2a848ce9, not a synthetic oracle.
Only CPU results; benchmark ratios are machine-local, not GPU parity.
"""
import json
import statistics
import sys
import time
import unittest
import numpy as np

from software_gpu.graphics.shader import BlinnPhongShader, Matrix4, Vertex
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from typing import Tuple


class BaselineShader(BlinnPhongShader):
    def fragment_shader(self, varyings: dict) -> Tuple[int, int, int, int]:
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


class TestBlinnPhongHalfVectorCache(unittest.TestCase):
    def _pair(self, light=None, texture=None, shininess=32.0):
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
        return BaselineShader(**params), BlinnPhongShader(**params)

    def test_exact_randomized_colors_with_live_material_mutation(self):
        rng = np.random.default_rng(20261011)
        texture = rng.integers(0, 256, size=(16, 16, 3), dtype=np.uint8)
        for shininess in (0.0, 1.0, 32.0, 128.0):
            for img in (None, texture):
                ref, opt = self._pair(texture=img, shininess=shininess)
                for i in range(1600):
                    if i % 53 == 0:
                        lighting = rng.normal(size=3).astype(np.float32)
                        lighting = lighting / np.linalg.norm(lighting)
                        ref.light_dir[:] = lighting
                        opt.light_dir[:] = lighting
                        pigment = rng.random(3).astype(np.float32)
                        ref.diffuse_color[:] = pigment
                        opt.diffuse_color[:] = pigment
                    if i % 79 == 0:
                        ref.light_dir[:] = [0.0, 0.0, -1.0]
                        opt.light_dir[:] = [0.0, 0.0, -1.0]
                    normal = rng.normal(size=3).astype(np.float32)
                    uv = rng.uniform(-1.0, 2.0, size=2).astype(np.float32)
                    varying = {"normal": normal, "uv": uv}
                    with self.subTest(shininess=shininess, textured=img is not None, index=i):
                        self.assertEqual(ref.fragment_shader(varying), opt.fragment_shader(varying))

    def test_real_framebuffer_pixel_and_depth_byte_parity(self):
        rng = np.random.default_rng(20261011)
        texture = rng.integers(0, 256, size=(16, 16, 3), dtype=np.uint8)
        vertices = [
            Vertex(np.array([-0.92, -0.87, 0.30]), normal=np.array([0.20, 0.30, 1.00]), uv=np.array([0.05, 0.91])),
            Vertex(np.array([ 0.90, -0.85, 0.30]), normal=np.array([1.00, 0.20, 0.15]), uv=np.array([0.90, 0.85])),
            Vertex(np.array([ 0.10,  0.94, 0.30]), normal=np.array([-0.2, 1.0, 0.5]), uv=np.array([0.50, 0.05])),
            Vertex(np.array([-0.68, -0.43, 0.15]), normal=np.array([0.4, -0.1, 1.0]), uv=np.array([0.05, 0.77])),
            Vertex(np.array([ 0.88, -0.14, 0.15]), normal=np.array([0.0, 0.3, 1.0]), uv=np.array([0.95, 0.13])),
            Vertex(np.array([-0.11,  0.70, 0.15]), normal=np.array([0.7, 0.6, 0.6]), uv=np.array([0.41, 0.35])),
        ]
        faces = [(0, 1, 2), (3, 4, 5)]
        for backend in ("bands", "tiles"):
            for textured in (False, True):
                ref, opt = self._pair(texture=texture if textured else None)
                results = []
                for shader in (ref, opt):
                    fb = Framebuffer(80, 80)
                    fb.clear(17, 19, 23, 255, depth=1.0)
                    renderer = SoftwareRasterizer(fb, backend=backend,
                                                  num_threads=2, tile_size=16)
                    try:
                        renderer.draw_mesh(vertices, faces, shader)
                    finally:
                        renderer.executor.shutdown(wait=True)
                    results.append((fb.color_buffer.copy(), fb.depth_buffer.copy()))
                with self.subTest(backend=backend, textured=textured):
                    self.assertGreater(np.count_nonzero(results[0][1] < 1.0), 50)
                    np.testing.assert_array_equal(results[0][0], results[1][0])
                    np.testing.assert_array_equal(results[0][1], results[1][1])

    def test_paired_true_fragment_execution_no_material_regression(self):
        rng = np.random.default_rng(20261011)
        normals = [rng.normal(size=3).astype(np.float32) for _ in range(800)]
        uv = np.array([0.45, 0.58], dtype=np.float32)
        ref, opt = self._pair()
        before, after = [], []
        for round_no in range(15):
            order = ((ref, before), (opt, after))
            if round_no % 2:
                order = tuple(reversed(order))
            for shader, samples in order:
                start = time.perf_counter_ns()
                for normal in normals:
                    shader.fragment_shader({"normal": normal, "uv": uv})
                samples.append((time.perf_counter_ns() - start) / 1e6)
        median_before = statistics.median(before)
        median_after = statistics.median(after)
        speedup = median_before / median_after
        print("BLINN_PHONG_PAIRED_CPU_EVIDENCE " + json.dumps({
            "python": sys.version.split()[0], "numpy": np.__version__,
            "rounds": 15, "normals_per_round": len(normals),
            "before_median_ms": round(median_before, 5),
            "after_median_ms": round(median_after, 5),
            "paired_speedup": round(statistics.median([x / y for x, y in zip(before, after)]), 4),
            "median_ratio": round(speedup, 4),
            "scope": "fragment function only",
        }, sort_keys=True))
        if sys.platform.startswith("linux") and sys.version_info >= (3, 12):
            self.assertGreaterEqual(speedup, 1.0, "fragment time regressed on canonical CPU lane")



    def test_paired_real_cpu_raster_time_and_byte_parity(self):
        from software_gpu.benchmarks.compare_tile_backends import make_fixture
        mesh, faces = make_fixture(8, 0.8)
        ref, opt = self._pair()
        frames = []
        for shader in (ref, opt):
            fb = Framebuffer(72, 72)
            engine = SoftwareRasterizer(fb, backend="tiles", tile_size=16,
                                        num_threads=1)
            frames.append((fb, engine, shader, []))
        try:
            for cycle in range(16):  # one warmup, 15 interleaved measurements
                order = (frames if cycle % 2 == 0 else list(reversed(frames)))
                for fb, engine, shader, samples in order:
                    fb.clear(0, 0, 0, 255, depth=1.0)
                    start = time.perf_counter_ns()
                    engine.draw_mesh(mesh, faces, shader)
                    elapsed = (time.perf_counter_ns() - start) / 1e6
                    if cycle:
                        samples.append(elapsed)
            np.testing.assert_array_equal(frames[0][0].color_buffer, frames[1][0].color_buffer)
            np.testing.assert_array_equal(frames[0][0].depth_buffer, frames[1][0].depth_buffer)
            self.assertGreater(np.count_nonzero(frames[0][0].depth_buffer < 1.0), 25)
            before, after = frames[0][3], frames[1][3]
            median_ratio = statistics.median(before) / statistics.median(after)
            print("BLINN_PHONG_RASTER_CPU_EVIDENCE " + json.dumps({
                "python": sys.version.split()[0], "numpy": np.__version__,
                "scene": "make_fixture(8,0.8)", "pixels": 72, "repeats": 15,
                "backend": "tiles", "workers": 1, "byte_identical": True,
                "before_median_ms": round(statistics.median(before), 5),
                "after_median_ms": round(statistics.median(after), 5),
                "median_ratio": round(median_ratio, 4),
                "scope": "full draw_mesh CPU rasterization on same host",
            }, sort_keys=True))
            if sys.platform.startswith("linux") and sys.version_info >= (3, 12):
                self.assertGreaterEqual(median_ratio, 0.95,
                                        "full CPU rasterization regressed >5%")
        finally:
            for _, engine, _, _ in frames:
                engine.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
