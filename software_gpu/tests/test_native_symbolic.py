"""Execute compiled C++ against real renderer f32 oracles, including failures."""
import copy
import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from software_gpu.research.native_symbolic import FLAGS, NATIVE, build_native, compiler, emit_cpp, encode_frames, main as build_main
from software_gpu.research.symbolic_wave import plan_ir
from software_gpu.tests.test_symbolic_wave import fixture, inputs, oracle, room_graph, room_oracle


class TestNativeSymbolic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A missing compiler fails CI; a skip is not evidence of native execution.
        compiler()
        cls.temp=tempfile.TemporaryDirectory(prefix='are-native-test-')
        cls.ir=fixture()
        cls.exe,cls.build=build_native(cls.ir,Path(cls.temp.name)/'edge')
        cls.rooms=room_graph()
        cls.room_exe,_=build_native(cls.rooms,Path(cls.temp.name)/'rooms')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def execute(self, ir, frames, executable=None, mode='incremental'):
        result=subprocess.run([str(executable or self.exe),'run',mode],input=encode_frames(ir,frames),
                              capture_output=True,check=True,timeout=20)
        return json.loads(result.stdout)['frames']

    def assert_oracle(self, results, frames, oracle_fn, output_count=1):
        for actual,frame in zip(results,frames):
            self.assertEqual(actual['status'],'PASS')
            self.assertEqual(len(actual['bits']),output_count)
            self.assertEqual(actual['bits'][0],oracle_fn(frame).view(np.uint32).ravel().tolist())

    def test_real_fused_and_incremental_edge_fuzz_and_standalone_binary(self):
        frames=[inputs(self.ir,seed) for seed in range(24)]
        for mode in ('fused','incremental','direct'):
            self.assert_oracle(self.execute(self.ir,frames,mode=mode),frames,oracle)
        self.assertEqual(self.build['binary_sha256'],hashlib.sha256(self.exe.read_bytes()).hexdigest())
        # Execute a copied native binary with no Python/module/source paths.
        copied=Path(self.temp.name)/self.exe.name
        copied.write_bytes(self.exe.read_bytes());copied.chmod(0o755)
        result=subprocess.run([str(copied),'info'],capture_output=True,check=True,text=True,
                              env={**os.environ,'PYTHONHOME':'missing','PYTHONPATH':'missing'})
        self.assertFalse(json.loads(result.stdout)['python_in_runtime'])

    def test_native_local_edits_cache_and_room_reduction(self):
        for ir,exe,changed_name,expected_nodes,reference in (
            (self.ir,self.exe,'px',3,oracle),(self.rooms,self.room_exe,'x0',6,room_oracle)):
            initial=inputs(ir,991)
            changed={k:v.copy() for k,v in initial.items()};changed[changed_name].flat[0]+=np.float32(.25)
            all_changed={k:v+np.float32(.5) for k,v in initial.items()}
            frames=[initial,initial,changed,all_changed,all_changed]
            actual=self.execute(ir,frames,exe)
            self.assert_oracle(actual,frames,reference)
            full=sum(n['op']!='input' for n in ir['nodes'])
            self.assertEqual([r['executed_nodes'] for r in actual],[full,0,expected_nodes,full,0])
            self.assertEqual(actual[2]['changed_inputs'],1)
            self.assert_oracle(self.execute(ir,frames,exe,'fused'),frames,reference)

    def test_signed_zero_subnormal_and_rounding_order(self):
        frames=[]
        for seed in range(4):
            data=inputs(self.ir,seed)
            data['px'].flat[:4]=np.array([0.,-0.,1e-45,-1e-45],np.float32)
            data['ax'].fill(0);data['ay'].fill(0);data['py'].fill(0);data['bx'].fill(1);data['by'].fill(1)
            frames.append(data)
        for mode in ('fused','incremental','direct'):
            self.assert_oracle(self.execute(self.ir,frames,mode=mode),frames,oracle)
        # (1e20 + -1e20) + 3 differs from 1e20 + (-1e20 + 3).
        ir=room_graph(2)
        ir['nodes']=[n for n in ir['nodes'] if n['id'] not in ('y1','r1')]
        for n in ir['nodes']:
            if n['id']=='r0':n.update(op='add',color='green')
            if n['id'].startswith('sum'):n['deps']=['r0','x1']
        exe,_=build_native(ir,Path(self.temp.name)/'rounding')
        data={'x0':np.array([1e20],np.float32),'y0':np.array([-1e20],np.float32),'x1':np.array([3],np.float32)}
        for mode in ('fused','incremental','direct'):
            actual=self.execute(ir,[data],exe,mode)
            self.assertEqual(actual[0]['bits'],[[1077936128]])

    def test_failed_frame_does_not_poison_cache(self):
        good=inputs(self.ir,13)
        overflow={k:v.copy() for k,v in good.items()}
        overflow['bx'].fill(1e30);overflow['py'].fill(1e30)
        frames=[good,overflow,good]
        for mode in ('fused','incremental','direct'):
            actual=self.execute(self.ir,frames,mode=mode)
            self.assertEqual(actual[1],{'status':'ERROR','reason':'NONFINITE_RESULT'})
            self.assertEqual(actual[0]['bits'],actual[2]['bits'])
            self.assertEqual(actual[2]['changed_inputs'],None if mode=='direct' else 0)
            if mode=='incremental':self.assertEqual(actual[2]['executed_nodes'],0)
        payload=bytearray(encode_frames(self.ir,[good,good,good]))
        cells=sum(v.size for v in good.values())
        struct.pack_into('<I',payload,48+cells*4,0x7fc00000)
        result=subprocess.run([str(self.exe),'run','incremental'],input=payload,capture_output=True,check=True)
        actual=json.loads(result.stdout)['frames']
        self.assertEqual(actual[1]['reason'],'NONFINITE_INPUT')
        self.assertEqual(actual[2]['executed_nodes'],0)

    def test_wire_and_cli_reject_malformed_bounded_inputs(self):
        payload=encode_frames(self.ir,[inputs(self.ir)])
        bad=[b'',b'BADMAGIC'+payload[8:],payload[:-1],payload+b'x',payload[:16]+bytes(32)+payload[48:],
             payload[:8]+struct.pack('<I',33)+payload[12:],
             payload[:12]+struct.pack('<I',1)+payload[16:]]
        for value in bad:
            result=subprocess.run([str(self.exe),'run','fused'],input=value,capture_output=True)
            self.assertEqual(result.returncode,2)
            self.assertIn(b'NATIVE_REJECTED',result.stderr)
        for args in ([],['run','unknown'],['bench','14','1'],['bench','15','0'],['bench','15','1x'],['invalid','a']):
            result=subprocess.run([str(self.exe),*args],input=b'',capture_output=True)
            self.assertEqual(result.returncode,2)

    def test_multiple_shapes_and_input_outputs(self):
        ir=fixture()
        extra=copy.deepcopy(ir['nodes'][0]);extra.update(id='extra',shape=[2])
        ir['nodes'].append(extra);ir['outputs']+=['ax','extra']
        exe,_=build_native(ir,Path(self.temp.name)/'multiple')
        data=inputs(ir)
        for mode in ('fused','incremental','direct'):
            results=self.execute(ir,[data,data],exe,mode)
            self.assert_oracle(results,[data,data],oracle,3)
            self.assertEqual(results[0]['bits'][1],data['ax'].view(np.uint32).ravel().tolist())
            self.assertEqual(results[0]['bits'][2],data['extra'].view(np.uint32).ravel().tolist())
        only={**ir,'nodes':[extra],'outputs':['extra']}
        exe,_=build_native(only,Path(self.temp.name)/'input-only')
        self.assertEqual(self.execute(only,[{'extra':data['extra']}],exe)[0]['executed_nodes'],0)

    def test_benchmark_is_native_batched_and_reports_all_samples(self):
        a=inputs(self.ir,991);b={k:v.copy() for k,v in a.items()};b['px'].flat[0]+=np.float32(.25)
        result=subprocess.run([str(self.exe),'bench','15','2'],input=encode_frames(self.ir,[a,b]),
                              capture_output=True,check=True,timeout=20)
        data=json.loads(result.stdout)
        self.assertEqual(data['last_incremental_executed_nodes'],3)
        self.assertEqual(data['frames_per_sample'],4)
        self.assertEqual(set(data['samples_ns']),{'fused-kernel','fused-checked','incremental-checked','direct-checked'})
        self.assertTrue(all(len(v)==15 and min(v)>0 for v in data['samples_ns'].values()))
        self.assertEqual(data['result_bits'],[oracle(a).view(np.uint32).ravel().tolist()])

    def test_direct_checks_unused_inputs_and_preserves_input_error_priority(self):
        ir=fixture()
        extra=copy.deepcopy(ir['nodes'][0]);extra.update(id='unused',shape=[3])
        ir['nodes'].append(extra)
        exe,_=build_native(ir,Path(self.temp.name)/'unused-input')
        good=inputs(ir,991)
        plan=plan_ir(ir)
        offsets={};offset=0
        for name in plan.inputs:
            offsets[name]=offset;offset+=good[name].size
        # Raw wire injection bypasses offline finite validation deliberately.
        # Cover NaN/Inf in every input, including the unconsumed, other-shape one.
        for name in plan.inputs:
            for bits in (0x7fc00000,0x7f800000,0xff800000):
                payload=bytearray(encode_frames(ir,[good,good,good]))
                struct.pack_into('<I',payload,48+4*(offset+offsets[name]),bits)
                result=subprocess.run([str(exe),'run','direct'],input=payload,capture_output=True,check=True)
                rows=json.loads(result.stdout)['frames']
                self.assertEqual(rows[1],{'status':'ERROR','reason':'NONFINITE_INPUT'})
                self.assertEqual(rows[0]['bits'],rows[2]['bits'])
                self.assertIsNone(rows[2]['changed_inputs'])
        # Even when arithmetic overflows, an invalid input wins classification.
        overflow={k:v.copy() for k,v in good.items()}
        overflow['bx'].fill(1e30);overflow['py'].fill(1e30)
        payload=bytearray(encode_frames(ir,[overflow]))
        struct.pack_into('<I',payload,48+4*offsets['unused'],0x7fc00000)
        result=subprocess.run([str(exe),'run','direct'],input=payload,capture_output=True,check=True)
        self.assertEqual(json.loads(result.stdout)['frames'][0]['reason'],'NONFINITE_INPUT')
        only={**ir,'nodes':[extra],'outputs':['unused']}
        exe,_=build_native(only,Path(self.temp.name)/'direct-input-only')
        payload=bytearray(encode_frames(only,[{'unused':good['unused']}]))
        struct.pack_into('<I',payload,48,0x7fc00000)
        result=subprocess.run([str(exe),'run','direct'],input=payload,capture_output=True,check=True)
        self.assertEqual(json.loads(result.stdout)['frames'][0]['reason'],'NONFINITE_INPUT')

    def test_direct_recomputes_all_nodes_with_unknown_change_count(self):
        for ir,exe,reference in ((self.ir,self.exe,oracle),(self.rooms,self.room_exe,room_oracle)):
            a=inputs(ir,991);b={k:v+np.float32(.25) for k,v in a.items()}
            frames=[a,a,b,a]
            actual=self.execute(ir,frames,exe,'direct')
            self.assert_oracle(actual,frames,reference)
            for row in actual:
                self.assertIsNone(row['changed_inputs'])
                self.assertEqual(row['executed_nodes'],sum(n['op']!='input' for n in ir['nodes']))

    def test_offline_build_and_input_validation(self):
        with self.assertRaises(ValueError):emit_cpp({})
        for frames in ([],[inputs(self.ir)]*33):
            with self.assertRaisesRegex(ValueError,'FRAME_BUDGET'):encode_frames(self.ir,frames)
        with patch('shutil.which',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'COMPILER_REQUIRED'):compiler()
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],1,'','bad compiler')):
            with self.assertRaisesRegex(RuntimeError,'BUILD_FAILED'):
                build_native(self.ir,Path(self.temp.name)/'failed')
        self.assertIn(plan_ir(self.ir).sha256,emit_cpp(self.ir))
        # CLI builds a real executable, not a mocked compiler.
        stdout=io.StringIO()
        with patch('sys.argv',['native_symbolic','--ir',str(Path(__file__).parent/'fixtures'/'symbolic-edge.ir.json'),
                               '--output-dir',str(Path(self.temp.name)/'cli')]), contextlib.redirect_stdout(stdout):
            build_main()
        self.assertTrue(Path(json.loads(stdout.getvalue())['executable']).is_file())

    def test_native_invariants_without_python_callbacks(self):
        exe=Path(self.temp.name)/('core-tests.exe' if os.name=='nt' else 'core-tests')
        subprocess.run([compiler(),*FLAGS,str(NATIVE/'core_tests.cpp'),'-o',str(exe)],
                       capture_output=True,check=True,timeout=120)
        result=subprocess.run([str(exe)],capture_output=True,check=True,text=True,timeout=20)
        self.assertIn('NATIVE_CORE_INVARIANTS_PASS',result.stdout)
        result=subprocess.run([compiler(),*FLAGS,'-ffast-math',str(NATIVE/'core_tests.cpp'),'-o',str(exe)],
                              capture_output=True,text=True,timeout=120)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Fast math violates ordered-f32-v1',result.stderr)
