"""Issue #3: observable clip, numerical rejection and shared-edge regression."""
import unittest
import numpy as np
from software_gpu.graphics.shader import Vertex, Shader
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.postprocess import MSAAFramebuffer, MSAARasterizer
from software_gpu.graphics.geometry import prepare_triangles

class ConstantShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {"color": vertex.color}
    def fragment_shader(self, varyings):
        color = np.clip(varyings["color"] * 255, 0, 255).astype(np.uint8)
        return (int(color[0]), int(color[1]), int(color[2]), 255)

def triangle(points, color=(1, 0, 0)):
    return [Vertex(np.asarray(p, dtype=np.float32), color=np.asarray(color, dtype=np.float32)) for p in points]

class TestClippingContract(unittest.TestCase):
    def setUp(self):
        self.shader = ConstantShader()

    def render(self, points, backend="tiles", workers=2):
        fb = Framebuffer(64, 64)
        fb.clear(0, 0, 0, 255)
        renderer = SoftwareRasterizer(fb, num_threads=workers, tile_size=16, backend=backend)
        try:
            renderer.draw_mesh(triangle(points), [(0, 1, 2)], self.shader)
        finally:
            renderer.executor.shutdown(wait=True)
        return fb

    def test_near_plane_triangle_is_clipped_not_discarded(self):
        points=[(-.7,-.6,-1.6,1.), (.7,-.6,0.,1.), (0.,.7,0.,1.)]
        reference=self.render(points,"bands",1)
        self.assertGreater(np.count_nonzero(reference.depth_buffer < 1), 40)
        for mode in ("tiles", "bands"):
            result=self.render(points,mode)
            np.testing.assert_array_equal(result.color_buffer, reference.color_buffer)
            self.assertTrue(np.isfinite(result.depth_buffer).all())

    def test_rejects_nonfinite_and_fully_outside(self):
        for pts in (
            [(-.6,-.6,0,1),(.6,-.6,0,1),(0,.6,np.nan,1)],
            [(-.6,-.6,0,1),(.6,-.6,0,1),(0,.6,np.inf,1)],
            [(-.6,-.6,-3,1),(.6,-.6,-3,1),(0,.6,-3,1)],
            [(-.6,-.6,0,0),(.6,-.6,0,0),(0,.6,0,0)],
        ):
            with self.subTest(pts=pts):
                result=self.render(pts)
                self.assertEqual(np.count_nonzero(result.depth_buffer < 1),0)
                self.assertTrue(np.isfinite(result.depth_buffer).all())

    def test_shared_edge_is_owned_once(self):
        left=triangle([(-.5,-.5,0),(.5,-.5,0),(-.5,.5,0)], (1,0,0))
        right=triangle([(.5,-.5,0),(.5,.5,0),(-.5,.5,0)], (0,1,0))
        for mode in ("bands","tiles"):
            fb=Framebuffer(64,64)
            fb.clear(0,0,0,255)
            renderer=SoftwareRasterizer(fb,tile_size=8,num_threads=3,backend=mode)
            try:
                renderer.draw_mesh(left,[(0,1,2)],self.shader)
                renderer.draw_mesh(right,[(0,1,2)],self.shader)
            finally:
                renderer.executor.shutdown(wait=True)
            self.assertEqual(np.count_nonzero(fb.depth_buffer<1),32*32)
            self.assertTrue(np.all(fb.depth_buffer[16:48,16:48]<1))

    def test_msaa_near_clip_and_finite(self):
        verts=triangle([(-.7,-.6,-1.6,1.),(.7,-.6,0.,1.),(0.,.7,0.,1.)])
        msaa=MSAAFramebuffer(64,64)
        msaa.clear(0,0,0,255)
        MSAARasterizer(msaa).draw_mesh(verts,[(0,1,2)],self.shader)
        self.assertGreater(np.count_nonzero(msaa.depth_samples < 1),40)
        self.assertTrue(np.isfinite(msaa.resolve().depth_buffer).all())

if __name__=="__main__":
    unittest.main()
