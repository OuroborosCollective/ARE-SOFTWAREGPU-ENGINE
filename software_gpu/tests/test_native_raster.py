"""Real compiled raster tests; bit comparisons include depth, not just images."""
import copy
import ctypes
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.geometry import prepare_triangles
from software_gpu.graphics.native_raster import NativeRasterKernel, NATIVE, build_raster_kernel, pack_triangles
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex
from software_gpu.graphics.surface_plan import BATCH_FIRST_POLICY
from software_gpu.graphics.tile_backend import rasterize_tiles
from software_gpu.benchmarks.compare_surface_plans import SCENES, build_scene
from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.research.native_symbolic import FLAGS, compiler


class TestNativeRaster(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='are-raster-test-')
        cls.binary, cls.receipt = build_raster_kernel(cls.temp.name)
        cls.kernel = NativeRasterKernel(cls.binary, cls.receipt['binary_sha256'])

    @classmethod
    def tearDownClass(cls):
        # Windows will keep the loaded DLL locked until this process exits.
        if __import__('sys').platform == 'win32':
            cls.temp._finalizer.detach()
        else:
            cls.temp.cleanup()

    def render(self, mesh, faces, width, height, backend):
        fb = Framebuffer(width, height); fb.clear()
        renderer = SoftwareRasterizer(fb, backend=backend, num_threads=1,
            native_kernel=self.kernel if backend == 'native-cpp' else None,
            plan_policy=BATCH_FIRST_POLICY if backend == 'tiles-plan' else None)
        try:
            renderer.draw_mesh(mesh, faces, VertexColorShader())
        finally:
            renderer.executor.shutdown()
        if backend == 'native-cpp':
            receipt = renderer.last_native_receipt
            self.assertEqual(receipt['python_fragment_calls'], 0)
            self.assertGreaterEqual(receipt['candidate_samples'], receipt['covered_samples'])
            self.assertGreaterEqual(receipt['covered_samples'], receipt['shaded_samples'])
            self.assertIsNone(renderer.last_plan_receipt)
        return fb

    def parity(self, mesh, faces, width, height):
        actual = self.render(mesh, faces, width, height, 'native-cpp')
        for backend in ('tiles', 'tiles-plan'):
            ref = self.render(mesh, faces, width, height, backend)
            self.assertEqual(actual.color_buffer.tobytes(), ref.color_buffer.tobytes(), backend+' color')
            self.assertEqual(actual.depth_buffer.tobytes(), ref.depth_buffer.tobytes(), backend+' depth')
        return actual

    def test_real_scenes_and_rectangular_frames(self):
        for name, spec in SCENES:
            with self.subTest(scene=name):
                self.parity(*build_scene(spec), 64, 48)
        mesh, faces = make_fixture(8, .8)
        self.parity(mesh, faces, 129, 97)
        self.parity([], [], 1, 1)

    def test_seeded_clipping_perspective_slivers_and_nonfinite(self):
        for seed in range(16):
            rng = np.random.default_rng(seed)
            positions = rng.uniform(-2, 2, (42, 4)).astype(np.float32)
            positions[:, 3] = rng.uniform(.15, 2, 42)
            # Degenerate, sliver and zero/negative W cases.
            positions[1] = positions[0]; positions[4] = positions[3]+np.float32(1e-7)
            positions[6, 3] = 0; positions[9, 3] = -.3
            positions[12, 0] = np.nan
            mesh = [Vertex(p, color=rng.uniform(-.1, 1.1, 3).astype(np.float32)) for p in positions]
            faces = [(i, i+1, i+2) for i in range(0, 42, 3)]
            faces += [(c, b, a) for a, b, c in faces]
            with self.subTest(seed=seed):
                self.parity(mesh, faces, 17+seed, 19+seed)

    def test_top_left_shared_edges_and_submission_ties(self):
        points = [(-1,-1,0,1),(-1,1,0,1),(1,1,0,1),(1,-1,0,1)]
        red = [Vertex(np.array(p), color=np.array([1,0,0])) for p in points]
        green = [Vertex(np.array(p), color=np.array([0,1,0])) for p in points]
        faces = [(0,2,1),(0,3,2)]
        fb = self.parity(red+green, faces+[(a+4,b+4,c+4) for a,b,c in faces], 32, 32)
        self.assertTrue(np.all(fb.color_buffer == [255,0,0,255]))
        self.assertTrue(np.all(fb.depth_buffer == 0))

    def test_all_eight_mixed_precision_color_patterns(self):
        mesh, faces = make_fixture(8, .8)
        triangles = prepare_triangles(mesh, faces, VertexColorShader(), 48, 32)
        self.assertTrue(triangles)
        for mask in range(8):
            adjusted = copy.deepcopy(triangles)
            for tri in adjusted:
                for vertex in range(3):
                    tri[6+vertex]['color'] = tri[6+vertex]['color'].astype(np.float64 if mask & (1 << vertex) else np.float32)
            actual, ref = Framebuffer(48,32), Framebuffer(48,32)
            actual.clear(); ref.clear()
            self.kernel.draw(actual, adjusted, VertexColorShader())
            engine = SoftwareRasterizer(ref, num_threads=1)
            try:
                rasterize_tiles(ref, adjusted, VertexColorShader(),32,engine.executor,1)
            finally:
                engine.executor.shutdown()
            self.assertEqual(actual.color_buffer.tobytes(), ref.color_buffer.tobytes(), str(mask))
            self.assertEqual(actual.depth_buffer.tobytes(), ref.depth_buffer.tobytes(), str(mask))

    def test_explicit_backend_and_callback_rejection(self):
        fb = Framebuffer(8,8)
        for options in ({'backend':'native-cpp'}, {'backend':'native-cpp','native_kernel':self.kernel,'num_threads':2},
                        {'native_kernel':self.kernel}, {'backend':'native-cpp','native_kernel':self.kernel,'preparation_cache_bytes':1024}, {'backend':'native-cpp','native_kernel':self.kernel,'plan_policy':BATCH_FIRST_POLICY}):
            with self.assertRaises(ValueError): SoftwareRasterizer(fb,**options)
        engine = SoftwareRasterizer(fb, backend='native-cpp', native_kernel=self.kernel)
        class Custom(VertexColorShader): pass
        try:
            for shader in (Custom(), VertexColorShader()):
                shader.vertex_shader = Mock(side_effect=AssertionError('must never execute'))
                with self.assertRaisesRegex(ValueError,'SHADER_UNSUPPORTED'): engine.draw_mesh([],[],shader)
                shader.vertex_shader.assert_not_called()
            engine.draw_mesh([],[],VertexColorShader())
        finally:
            engine.executor.shutdown()
        shader = VertexColorShader(); shader.fragment_shader = lambda _: (0,0,0,0)
        with self.assertRaisesRegex(ValueError,'SHADER_UNSUPPORTED'): self.kernel.draw(fb,[],shader)

    def test_buffer_validation_and_no_implicit_copy(self):
        for bad in ('dtype','shape','strides','readonly','unaligned','alias','frame'):
            fb = Framebuffer(8,8)
            if bad == 'dtype': fb.depth_buffer = fb.depth_buffer.astype(np.float64)
            if bad == 'shape': fb.color_buffer = np.zeros((8,8,3),np.uint8)
            if bad == 'strides': fb.depth_buffer = fb.depth_buffer[:,::-1]
            if bad == 'readonly': fb.color_buffer.flags.writeable = False
            if bad == 'unaligned': fb.depth_buffer = np.ndarray((8,8),np.float32,buffer=bytearray(257),offset=1)
            if bad == 'alias': fb.depth_buffer = fb.color_buffer.view(np.float32).reshape(8,8)
            if bad == 'frame': fb.width = 5000
            before = fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.kernel.draw(fb,[],VertexColorShader())
            self.assertEqual(before,(fb.color_buffer.tobytes(),fb.depth_buffer.tobytes()))

    def test_late_invalid_record_and_work_budget_are_atomic(self):
        mesh, faces = make_fixture(8,.8)
        tri = prepare_triangles(mesh,faces,VertexColorShader(),64,64)[0]
        good = pack_triangles([tri])
        fb = Framebuffer(64,64);fb.clear()
        initial = fb.color_buffer.tobytes(),fb.depth_buffer.tobytes()
        for index, value in ((0,float('nan')),(0,1000),(2,3),(9,0),(12,0),(12,123),(13,1e10),(22,8),(22,.5)):
            packed = np.repeat(good,2,axis=0);packed[1,index]=value
            counts = np.full(3,99,np.uint64)
            status = self.kernel._call(packed.ctypes.data,packed.size,2,64,64,fb.color_buffer.ctypes.data,
                                      fb.color_buffer.nbytes,fb.depth_buffer.ctypes.data,fb.depth_buffer.size,counts.ctypes.data,3)
            self.assertEqual(status,4,(index,value));self.assertTrue(np.all(counts==99))
            self.assertEqual(initial,(fb.color_buffer.tobytes(),fb.depth_buffer.tobytes()))
        invalid = copy.deepcopy(tri);invalid[6]['color'][0]=1e10
        with self.assertRaisesRegex(ValueError,'REJECTED:4'):self.kernel.draw(fb,[tri,invalid],VertexColorShader())
        invalid[6]['color'] = [1,2,3]
        with self.assertRaisesRegex(ValueError,'COLOR_DOMAIN'):pack_triangles([invalid])
        with self.assertRaisesRegex(ValueError,'TRIANGLE_BUDGET'):pack_triangles([tri]*200001)
        packed = np.repeat(good,100000,axis=0)
        counts = np.full(3,99,np.uint64)
        self.assertEqual(self.kernel._call(packed.ctypes.data,packed.size,len(packed),64,64,
            fb.color_buffer.ctypes.data,fb.color_buffer.nbytes,fb.depth_buffer.ctypes.data,
            fb.depth_buffer.size,counts.ctypes.data,3),5)
        self.assertTrue(np.all(counts==99))
        self.assertEqual(initial,(fb.color_buffer.tobytes(),fb.depth_buffer.tobytes()))

    def test_hash_abi_and_build_errors(self):
        with self.assertRaisesRegex(ValueError,'BINARY_HASH'):NativeRasterKernel(self.binary,'0'*64)
        lib = Mock();lib.are_raster_abi.return_value=99
        with patch('ctypes.CDLL',return_value=lib), self.assertRaisesRegex(ValueError,'ABI'):
            NativeRasterKernel(self.binary,self.receipt['binary_sha256'])
        with patch('software_gpu.graphics.native_raster.subprocess.run',return_value=Mock(returncode=1,stderr='failure')):
            with self.assertRaisesRegex(RuntimeError,'BUILD_FAILED'):build_raster_kernel(Path(self.temp.name)/'failed')

    def test_standalone_cpp_contract_and_fastmath_rejection(self):
        exe = Path(self.temp.name)/('contracts.exe' if __import__('sys').platform=='win32' else 'contracts')
        subprocess.run([compiler(),*FLAGS,str(NATIVE/'raster/test.cpp'),'-o',str(exe)],check=True,capture_output=True,timeout=60)
        result = subprocess.run([str(exe)],check=True,capture_output=True,text=True,timeout=20)
        self.assertIn('PASS native raster',result.stdout)
        bad = subprocess.run([compiler(),*FLAGS,'-ffast-math','-c',str(NATIVE/'raster/test.cpp'),'-o',str(exe)+'.o'],
                             capture_output=True,text=True,timeout=60)
        self.assertNotEqual(bad.returncode,0)
        self.assertIn('Fast math violates ordered-f32-v1',bad.stderr)
