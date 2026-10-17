"""Real Blinn-Phong RGBA semantics before/after inlining scalar clamp.

CPU-only exact-output tests. Microbenchmark results are separately measured
with actual renderer invocations; no timing literals are used as evidence.
"""
import math
import unittest

import numpy as np

from software_gpu.graphics.shader import BlinnPhongShader, Matrix4


def reference_byte(value):
    if math.isnan(value):
        raise ValueError("cannot convert float NaN to integer")
    return int(min(1.0, max(0.0, value)) * 255.0)


def ambient_only(colors, ambient=(1.0, 1.0, 1.0)):
    # Use actual full lighting shader. Light energy = 0; all pixel channels
    # derive from the ambient term, with identical numpy float32 arithmetic.
    return BlinnPhongShader(
        model_matrix=Matrix4.identity(),
        view_matrix=Matrix4.identity(),
        proj_matrix=Matrix4.identity(),
        light_dir=np.array([0, 0, 1], dtype=np.float32),
        light_color=np.zeros(3, dtype=np.float32),
        diffuse_color=np.asarray(colors, dtype=np.float32),
        ambient_color=np.asarray(ambient, dtype=np.float32),
        specular_color=np.zeros(3, dtype=np.float32),
    )


class BlinnPhongScalarClipParity(unittest.TestCase):
    def test_finite_channels_against_existing_scalar_contract(self):
        candidates=(-3.0, -0.0, 0.0, 0.000001, 0.2, 0.5, 0.75,
                    0.99999994, 1.0, 1.0000001, 2.0)
        varying={"normal":np.array([0, 0, 1], dtype=np.float32),
                 "uv":np.array([0.5, 0.5], dtype=np.float32)}
        for color in candidates:
            shader=ambient_only((color, color / 2, -color))
            with self.subTest(color=color):
                actual=shader.fragment_shader(varying)
                triple=np.asarray((color, color / 2, -color), dtype=np.float32)
                expected=tuple(reference_byte(float(v)) for v in triple)+(255,)
                self.assertEqual(actual, expected)

    def test_nan_in_each_channel_keeps_explicit_value_error(self):
        varying={"normal":np.array([0, 0, 1], dtype=np.float32),
                 "uv":np.array([0.5, 0.5], dtype=np.float32)}
        for index in range(3):
            color=[0.3, 0.5, 0.7]
            color[index]=float("nan")
            shader=ambient_only(color)
            with self.subTest(channel=index):
                with self.assertRaisesRegex(ValueError, "cannot convert float NaN"):
                    shader.fragment_shader(varying)

    def test_infinite_ambient_channels_saturate_without_swallowing_nan(self):
        varying={"normal":np.array([0, 0, 1], dtype=np.float32),
                 "uv":np.array([0.5, 0.5], dtype=np.float32)}
        shader=ambient_only((1.0, 1.0, 0.5), (float("inf"), -float("inf"), 1.0))
        self.assertEqual(shader.fragment_shader(varying), (255, 0, 127, 255))


class VertexColorScalarParity(unittest.TestCase):
    @staticmethod
    def reference(color):
        rgb=np.clip(np.asarray(color)*255,0,255).astype(np.uint8)
        return int(rgb[0]), int(rgb[1]), int(rgb[2]), 255

    def test_32_and_64_bit_colors_exact_at_all_uint8_boundaries(self):
        from software_gpu.graphics.batch_shader import VertexColorShader
        rng=np.random.default_rng(20261017)
        shader=VertexColorShader()
        for dtype in (np.float32,np.float64):
            samples=[rng.uniform(-1.0,2.0,size=3).astype(dtype)
                     for _ in range(500)]
            for channel in (0,1,2):
                for value in (-1., -0., 0., 0.5, 1., 1.1, 10.):
                    sample=np.array([0.1,0.2,0.3],dtype=dtype)
                    sample[channel]=value
                    samples.append(sample)
                for k in (1,2,3,127,128,254,255):
                    pivot=dtype(k/255.)
                    for value in (np.nextafter(pivot,dtype(-np.inf)),
                                  pivot,np.nextafter(pivot,dtype(np.inf))):
                        sample=np.array([0.1,0.2,0.3],dtype=dtype)
                        sample[channel]=value
                        samples.append(sample)
            for index,color in enumerate(samples):
                with self.subTest(dtype=str(dtype),sample=index):
                    self.assertEqual(shader.fragment_shader({"color":color}),
                                     self.reference(color))

    def test_nan_infinity_and_other_dtypes_preserve_numpy_results(self):
        import warnings
        from software_gpu.graphics.batch_shader import VertexColorShader
        shader=VertexColorShader()
        examples=[
            np.array([np.nan, .5, 1.],dtype=np.float32),
            np.array([.1, np.inf, -.2],dtype=np.float32),
            np.array([.1, -np.inf, .2],dtype=np.float64),
            np.array([np.nan, 1., 0.],dtype=np.float64),
            np.array([.2, .5, .8],dtype=np.float16),
            np.array([3, -2, 1],dtype=np.int16),
            [.1, .5, 1.5],
        ]
        for color in examples:
            with self.subTest(color=str(color)):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore",RuntimeWarning)
                    expected=self.reference(color)
                    got=shader.fragment_shader({"color":color})
                self.assertEqual(got,expected)

    def test_real_render_rgba_and_float32_depth_match_batch_path(self):
        from software_gpu.graphics.batch_shader import VertexColorShader
        from software_gpu.graphics.framebuffer import Framebuffer
        from software_gpu.graphics.rasterizer import SoftwareRasterizer
        from software_gpu.graphics.shader import Vertex
        from software_gpu.graphics.surface_plan import BATCH_FIRST_POLICY
        positions=[
            (-.90,-.85,.40),(.80,-.85,.40),(-.10,.88,.40),
            (-.80,-.74,.28),(.94,-.74,.28),(.05,.90,.28),
        ]
        colors=[(.1,.2,.9),(.8,.9,.1),(.5,.2,.1),
                (.1,.5,.8),(.8,.1,.5),(.3,.9,.1)]
        mesh=[Vertex(np.asarray((*p,1.0),dtype=np.float32),
                     color=np.asarray(c,dtype=np.float32))
              for p,c in zip(positions,colors)]
        frames=[]
        for backend in ("tiles","tiles-plan"):
            fb=Framebuffer(80,80)
            fb.clear(13,17,23,255,depth=1.0)
            raster=SoftwareRasterizer(
                fb,backend=backend,tile_size=16,num_threads=2,
                plan_policy=BATCH_FIRST_POLICY if backend=="tiles-plan" else None)
            try:
                raster.draw_mesh(mesh,[(0,1,2),(3,4,5)],VertexColorShader())
                frames.append((fb.color_buffer.copy(),fb.depth_buffer.copy()))
            finally:
                raster.executor.shutdown(wait=True)
        self.assertGreater(np.count_nonzero(frames[0][1]<1.0),100)
        np.testing.assert_array_equal(frames[0][0],frames[1][0])
        np.testing.assert_array_equal(frames[0][1],frames[1][1])


class VertexColorBatchAllocationParity(unittest.TestCase):
    @staticmethod
    def reference(colors):
        # Original batch implementation, from the exact original renderer
        color=np.asarray(colors)
        if color.ndim!=2 or color.shape[1]!=3 or not np.isfinite(color).all():
            raise ValueError("BATCH_COLOR_INPUT_INVALID")
        rgb=np.clip(color*255,0,255).astype(np.uint8)
        rgba=np.empty((len(rgb),4),dtype=np.uint8)
        rgba[:,:3]=rgb
        rgba[:,3]=255
        return rgba

    def test_randomized_finite_batches_exact_and_do_not_mutate_inputs(self):
        from software_gpu.graphics.batch_shader import VertexColorShader
        rng=np.random.default_rng(20261017)
        shader=VertexColorShader()
        for count in (0,1,3,128,2048):
            for dtype in (np.float16,np.float32,np.float64,np.int16):
                color=(rng.uniform(-2.,3.,size=(count,3)).astype(dtype)
                       if np.issubdtype(dtype,np.floating)
                       else rng.integers(-3,4,size=(count,3),dtype=dtype))
                before=color.copy()
                with self.subTest(count=count,dtype=str(dtype)):
                    actual=shader.fragment_shader_batch({"color":color})
                    np.testing.assert_array_equal(actual,self.reference(color))
                    np.testing.assert_array_equal(color,before)
                    self.assertEqual(actual.shape,(count,4))
                    self.assertEqual(actual.dtype,np.uint8)
                    self.assertTrue(actual.flags.c_contiguous)

    def test_nonfinite_and_malformed_inputs_fail_closed(self):
        from software_gpu.graphics.batch_shader import VertexColorShader
        shader=VertexColorShader()
        invalid=(np.array([[np.nan,0.,1.]],dtype=np.float32),
                 np.array([[.1,np.inf,1.]],dtype=np.float64),
                 np.array([.1,.4,.8],dtype=np.float32),
                 np.zeros((2,4),dtype=np.float32))
        for sample in invalid:
            with self.subTest(shape=sample.shape):
                with self.assertRaisesRegex(ValueError,"BATCH_COLOR_INPUT_INVALID"):
                    shader.fragment_shader_batch({"color":sample})

    def test_float32_boundary_results_including_overbright(self):
        from software_gpu.graphics.batch_shader import VertexColorShader
        shader=VertexColorShader()
        pivot=np.linspace(-.1,1.1,4096,dtype=np.float32)
        color=np.stack((pivot,pivot[::-1],
                        np.nextafter(pivot,np.float32(np.inf))),axis=1)
        np.testing.assert_array_equal(shader.fragment_shader_batch({"color":color}),
                                      self.reference(color))



if __name__ == "__main__":
    unittest.main()
