"""Real GLB decoding, independent skin oracle, native buffers and bounded failures."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import numpy as np

from software_gpu.research.model_probe import load_asset, write_scene, run_model, build_model_probe, read_glb, accessor, decode_output
from software_gpu.tests.fixtures.model_fixture import make_glb
from tools.model_reference import pose


class TestModelProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='are-model-probe-')
        cls.root = Path(cls.temp.name)
        cls.exe, cls.build = build_model_probe(cls.root/'native')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def asset(self, **kwargs):
        path = self.root/'fixture.glb'
        entry = make_glb(path, **kwargs)
        return load_asset(path, entry)

    def run_asset(self, asset, times=(0,1,2,3), **kwargs):
        path = self.root/'request.bin'
        write_scene(path, [dict(asset=asset, clip=0 if asset['clips'] else None)], list(times), 64, 16)
        return run_model(self.exe, path, **kwargs)

    def test_twelve_influences_clamping_step_slerp_and_mesh_cancellation(self):
        a = self.asset(interleaved=True)
        times = [0, .2, 1, 2, 3]
        out = self.run_asset(a, times, mode='pose')
        for t, frame in zip(times,out['poses']):
            np.testing.assert_allclose(frame[0], pose(a,0,t), rtol=1e-13, atol=1e-13)
        # Wolfram's independent rational calculation: all twelve weighted joints.
        np.testing.assert_allclose(out['poses'][0][0][0], [28/3,2,3], atol=2e-7, rtol=0)
        self.assertGreater(abs(out['poses'][0][0][0,0]-4), 5)  # Dropping weights 5..12 is wrong.
        self.assertEqual(a['metadata']['maximum_nonzero_influences'],12)
        self.assertEqual(len(a['clips']),1)

    def test_parent_and_inverse_bind_and_static_matrix(self):
        a = self.asset()
        a['nodes'][2]['parent'] = 1
        a['inverse_bind'][1,0,3] = -2
        # Shortest-arc equivalent endpoint: sign-flipped quaternion.
        a['clips'][0]['channels'][0]['values'][1] = [0,0,-.7071067811865476,-.7071067811865476]
        out = self.run_asset(a,[.5,1.5],mode='pose')
        for t,f in zip([.5,1.5],out['poses']):
            np.testing.assert_allclose(f[0],pose(a,0,t),rtol=1e-13,atol=1e-13)
        a = self.asset(static=True)
        a['nodes'][0]['matrix'][:3,3] = [2,3,4]
        actual = self.run_asset(a,[0],mode='pose')['poses'][0][0]
        np.testing.assert_array_equal(actual,a['positions']+[2,3,4])

    def test_native_animation_frames_and_worker_parity(self):
        a = self.asset()
        one = self.run_asset(a,repeats=4,workers=1)
        four = self.run_asset(a,repeats=4,workers=4)
        for key in ('frames','resolved','depth'):
            np.testing.assert_array_equal(one[key],four[key])
        self.assertNotEqual(four['receipt']['frame_sha256'][0],four['receipt']['frame_sha256'][1])
        self.assertEqual(four['receipt']['frame_sha256'][2],four['receipt']['frame_sha256'][3])
        self.assertTrue(four['receipt']['full_buffer_parity'])
        self.assertFalse(self.build['python_in_runtime'])
        receipt=four['receipt']
        self.assertEqual(len(receipt['baseline_frame_timings']),4)
        self.assertEqual(len(receipt['candidate_frame_timings']),4)
        for frame in receipt['candidate_frame_timings']:
            self.assertEqual(frame['frame_total_ms'],receipt['candidate_total_ms'][frame['frame']])
            for field in ('animated_pose_ms','static_pose_ms','triangle_prepare_ms','handoff_ms',
                          'render_setup_ms','rasterization_ms','msaa_ms','aa_ms','scheduler_binning_ms'):
                self.assertGreaterEqual(frame[field],0)
            for field in ('render_setup_worker_work_ms','rasterization_worker_work_ms',
                          'msaa_worker_work_ms','aa_worker_work_ms'):
                self.assertGreaterEqual(frame[field],0)

    def test_uint32_primitive_ids_beyond_65535(self):
        small = self.run_asset(self.asset(static=True),[0],repeats=1)
        large = self.run_asset(self.asset(static=True,repeated_faces=65540),[0],repeats=1)
        self.assertEqual(large['receipt']['triangles'],65540)
        self.assertGreater(large['receipt']['sample_writes'][0],0)
        for key in ('frames','resolved','depth'):
            np.testing.assert_array_equal(small[key],large[key])

    def test_glb_failures_hash_bounds_scene_skin_and_animation(self):
        mutations = [
            lambda d,b: d.update(extensionsRequired=['unsupported']),
            lambda d,b: d['buffers'][0].update(uri='external.bin'),
            lambda d,b: d['accessors'][0].update(byteOffset=999999),
            lambda d,b: d['accessors'][0].update(sparse={}),
            lambda d,b: d['nodes'][1].update(children=[2]),
            lambda d,b: d['scenes'][0].update(nodes=[1]),
            lambda d,b: d['skins'][0].update(joints=[1]*12),
            lambda d,b: d['meshes'][0]['primitives'][0]['attributes'].pop('WEIGHTS_2'),
            lambda d,b: d['animations'][0]['samplers'][0].update(interpolation='CUBICSPLINE'),
            lambda d,b: d['animations'][0]['channels'][0]['target'].update(path='weights'),
            lambda d,b: d['materials'][0].update(alphaMode='BLEND'),
            lambda d,b: d['materials'][0].update(doubleSided=False),
            lambda d,b: d['nodes'][0].update(rotation=[0,0,0,0]),
            lambda d,b: d['meshes'][0]['primitives'][0].update(mode=1),
            lambda d,b: d.update(animations=d['animations']*65),
            lambda d,b: d['animations'][0].update(channels=d['animations'][0]['channels']*14),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                with self.assertRaises((ValueError,KeyError)):
                    self.asset(mutate=mutate)
        path = self.root/'hash.glb'; entry = make_glb(path)
        with self.assertRaisesRegex(ValueError,'MODEL_SOURCE_HASH'):
            read_glb(path,'0'*64,entry['bytes'])
        with self.assertRaisesRegex(ValueError,'MODEL_SOURCE_SIZE'):
            read_glb(path,entry['sha256'],entry['bytes']-1)
        raw = bytearray(path.read_bytes()); raw[0]=0; path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'MODEL_GLB_HEADER'):
            read_glb(path,hashlib.sha256(raw).hexdigest(),len(raw))
        # Integer normalization is meaningful for exported skin weights.
        d = dict(accessors=[dict(bufferView=0,componentType=5121,count=1,type='VEC4',normalized=True)],
                 bufferViews=[dict(byteLength=4)])
        np.testing.assert_array_equal(accessor(d,b'\x00\x55\xaa\xff',0),np.array([[0,1/3,2/3,1]],dtype='f4'))

    def test_corrupt_actual_native_response_rejected(self):
        a = self.asset(); path = self.root/'receipt.bin'
        write_scene(path,[dict(asset=a,clip=0)],[0],64,16)
        raw = subprocess.run([str(self.exe),str(path),'4','1','combined','render'],capture_output=True,check=True).stdout
        decode_output(raw,4,1,'combined')
        for bad in (b'',raw[:-1],raw+b'x',b'BADMAGIC'+raw[8:]):
            with self.assertRaises(ValueError):decode_output(bad,4,1,'combined')
        w,h,n,nj = struct.unpack_from('<4I',raw,8)
        good = json.loads(raw[24:24+nj])
        for field,value in [('full_buffer_parity',False),('hardware_gpu_submitted',True),('models',0),
                            ('candidate_total_ms',[float('nan')]),('sample_writes',[True]),
                            ('construction_fit_and_serial_reference_ms',-1),('candidate_frame_timings',[])]:
            bad = dict(good,**{field:value}); encoded = json.dumps(bad).encode()
            changed = raw[:8]+struct.pack('<4I',w,h,n,len(encoded))+encoded+raw[24+nj:]
            with self.subTest(field=field),self.assertRaises(ValueError):decode_output(changed,4,1,'combined')

    def test_native_rejects_invalid_graph_indices_weights_and_key_times(self):
        a = self.asset()
        changes = [('MODEL_NODE_CYCLE', lambda b: b['nodes'][1].update(parent=1)),
                   ('MODEL_INDEX',lambda b: b['faces'].__setitem__((0,0),99)),
                   ('MODEL_WEIGHT_SUM',lambda b: b['weights'].__setitem__((0,slice(None)),0)),
                   ('MODEL_KEY_TIME',lambda b: b['clips'][0]['channels'][0]['times'].__setitem__(1,0)),
                   ('MODEL_JOINT',lambda b: b['joints'].__setitem__(0,999)),
                   ('MODEL_POSITION',lambda b: b['positions'].__setitem__((0,0),np.nan))]
        for code,change in changes:
            b = copy.deepcopy(a); change(b)
            with self.subTest(code=code),self.assertRaisesRegex(RuntimeError,code):
                self.run_asset(b,[0],mode='pose')
        path = self.root/'request.bin'
        write_scene(path,[dict(asset=a,clip=0)],[0])
        data = path.read_bytes()
        for raw,code in [(data[:-1],'MODEL_TRUNCATED'),(data+b'x','MODEL_TRAILING'),(b'XXXXXXXX'+data[8:],'MODEL_PROTOCOL')]:
            path.write_bytes(raw)
            with self.assertRaisesRegex(RuntimeError,code):run_model(self.exe,path)

    def test_boundary_rejects_invalid_configuration(self):
        a = self.asset(); path = self.root/'request.bin'
        for kwargs in [dict(times=[]),dict(times=[float('nan')]),dict(times=[0],pixels=513),dict(times=[0],tile=1)]:
            with self.assertRaises(ValueError):write_scene(path,[dict(asset=a)],**kwargs)
        for extra in [dict(clip=99),dict(color=[1,2,3]),dict(placement=np.zeros((4,4)))]:
            with self.assertRaises(ValueError):write_scene(path,[dict(asset=a,**extra)],[0])
        for kwargs in [dict(workers=True),dict(repeats=0),dict(timeout=0),dict(policy='unknown'),dict(mode='unknown')]:
            with self.assertRaises(ValueError):run_model(self.exe,path,**kwargs)


if __name__ == '__main__':
    unittest.main()
