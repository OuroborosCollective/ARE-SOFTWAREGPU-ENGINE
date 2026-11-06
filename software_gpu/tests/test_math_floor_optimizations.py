import unittest
import time
import numpy as np

class PerfTest(unittest.TestCase):
    def test_rasterizer_perf(self):
        from software_gpu.graphics.rasterizer import SoftwareRasterizer
        from software_gpu.graphics.framebuffer import Framebuffer
        from software_gpu.graphics.shader import Shader, Vertex, BlinnPhongShader, Matrix4

        width, height = 128, 128
        fb = Framebuffer(width, height)
        fb.clear(r=10, g=10, b=10, a=255, depth=1.0)

        # generate a bunch of triangles
        vertices = []
        indices = []
        n_tris = 100
        np.random.seed(42)
        for i in range(n_tris):
            x = np.random.uniform(-1.0, 1.0)
            y = np.random.uniform(-1.0, 1.0)
            z = np.random.uniform(0.1, 1.0)
            sz = 0.1
            vertices.append(Vertex(position=np.array([x, y, z]), color=np.array([1.0, 0.0, 0.0])))
            vertices.append(Vertex(position=np.array([x+sz, y, z]), color=np.array([1.0, 0.0, 0.0])))
            vertices.append(Vertex(position=np.array([x, y+sz, z]), color=np.array([1.0, 0.0, 0.0])))
            indices.append((i*3, i*3+1, i*3+2))

        model = Matrix4.identity()
        view = Matrix4.look_at(
            eye=np.array([0.0, 0.0, 2.0]),
            target=np.array([0.0, 0.0, 0.0]),
            up=np.array([0.0, 1.0, 0.0])
        )
        proj = Matrix4.perspective(fov_rad=np.radians(60.0), aspect=1.0, near=0.1, far=10.0)

        shader = BlinnPhongShader(model, view, proj, diffuse_color=np.array([1.0, 0.0, 0.0]))

        rasterizer = SoftwareRasterizer(fb, backend="bands")
        start = time.perf_counter()
        rasterizer.draw_mesh(vertices, indices, shader)
        end = time.perf_counter()

        duration = end - start
        self.assertLess(duration, 0.5)

if __name__ == '__main__':
    unittest.main()
