"""Full-buffer differential coverage against the frozen pre-optimization bands."""
import unittest
import numpy as np
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex
from software_gpu.tests.fixtures.band_reference import _rasterize_band
from software_gpu.tests.test_raster_correctness_contract import AlphaShader, clip_quad


class ReferenceRasterizer(SoftwareRasterizer):
    _rasterize_band = _rasterize_band


def scenes():
    """Deterministic real clip-space meshes, including one-ULP pixel boundaries."""
    yield 'perspective', *clip_quad(.13, .87)
    rng = np.random.default_rng(1234)
    for seed in range(12):
        vertices, faces = [], []
        for i in range(8):
            xyz = rng.uniform(-1.4, 1.4, (3, 3))
            w = rng.uniform(.2, 2, 3)
            for j in range(3):
                vertices.append(Vertex(np.r_[xyz[j] * w[j], w[j]],
                                       color=rng.random(3), uv=np.array([37 + i, 0.])))
            faces.append((3*i, 3*i+1, 3*i+2))
        yield 'seeded-clip-'+str(seed), vertices, faces
    # 32px screen coordinates: shared diagonal, horizontal/vertical edges,
    # viewport extremes, subpixel slivers and a degenerate primitive.
    for shift in (np.float32(0), np.float32(2**-20), np.float32(-2**-20)):
        points = [(0.5, .5), (.5, 31.5), (31.5, .5), (31.5, 31.5),
                  (-2, 16), (34, 16), (16, 16+2**-16), (16, 16)]
        vertices = [Vertex(np.array([(x+shift)/16-1, 1-(y+shift)/16, .3 + i*.01, 1.]),
                           color=np.array([i/8, .7, .2]), uv=np.array([13+i, 0.]))
                    for i, (x,y) in enumerate(points)]
        yield 'pixel-boundary-'+str(shift), vertices, [(0,2,1),(2,3,1),(4,5,6),(7,7,7)]
    # Duplicate geometry with different colors and flat alpha; near/far/tie order.
    for depths in ((.25,.25), (.25,.75), (.75,.25)):
        vertices=[]
        for i,z in enumerate(depths):
            vertices.extend(Vertex(np.array([x,y,z,1.]), color=np.eye(3)[i],
                                   uv=np.array([23+100*i,0.]))
                            for x,y in ((-.8,-.8),(.8,-.8),(0,.8)))
        yield 'depth-'+str(depths), vertices, [(0,1,2),(3,4,5)]
    for bad in (np.nan, np.inf, -np.inf):
        vertices=[Vertex(np.array([x,y,.3,1.]),color=np.ones(3),uv=np.array([91.,0.]))
                  for x,y in ((-.8,-.8),(.8,-.8),(0,.8))]
        vertices.append(Vertex(np.array([bad,0,.3,1.]),color=np.ones(3)))
        yield 'nonfinite-'+str(bad), vertices, [(0,1,2),(0,1,3)]


def render(cls, vertices, faces, width=32, height=32, workers=1):
    fb=Framebuffer(width,height)
    fb.clear(11,23,37,59,depth=1.)
    engine=cls(fb,backend='bands',num_threads=workers,tile_size=8)
    try:
        engine.draw_mesh(vertices,faces,AlphaShader())
    finally:
        engine.executor.shutdown(wait=True)
    return fb


class TestBandInlineParity(unittest.TestCase):
    def test_complete_rgba8_and_float32_depth_bytes(self):
        for name,vertices,faces in scenes():
            for width,height,workers in ((32,32,1),(37,19,3),(1,1,1)):
                with self.subTest(scene=name,size=(width,height),workers=workers):
                    a=render(ReferenceRasterizer,vertices,faces,width,height,workers)
                    b=render(SoftwareRasterizer,vertices,faces,width,height,workers)
                    self.assertEqual(a.color_buffer.tobytes(),b.color_buffer.tobytes())
                    self.assertEqual(a.depth_buffer.tobytes(),b.depth_buffer.tobytes())

    def test_shared_diagonal_shades_each_sample_once(self):
        class CountingShader(AlphaShader):
            def __init__(self): self.calls=0
            def fragment_shader(self,varyings):
                self.calls+=1
                return super().fragment_shader(varyings)
        # Clear depth after each triangle: a double-owned edge cannot hide behind early-Z.
        vertices=[Vertex(np.array([x,y,0.,1.]),color=np.ones(3),uv=np.array([81.,0.]))
                  for x,y in ((-1,-1),(1,-1),(-1,1),(1,1))]
        fb=Framebuffer(32,32); engine=SoftwareRasterizer(fb,backend='bands',num_threads=1)
        shader=CountingShader(); masks=[]
        try:
            for face in ((0,1,2),(1,3,2)):
                fb.clear(0,0,0,0,depth=1.)
                engine.draw_mesh(vertices,[face],shader)
                masks.append(fb.depth_buffer<1.)
        finally: engine.executor.shutdown(wait=True)
        self.assertFalse(np.any(masks[0]&masks[1]))
        self.assertTrue(np.all(masks[0]|masks[1]))
        self.assertEqual(shader.calls,1024)
