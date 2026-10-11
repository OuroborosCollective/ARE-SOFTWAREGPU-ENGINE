#!/usr/bin/env python3
"""Build once; all repeated native work runs inside an independent C++ process."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from software_gpu.research.native_symbolic import build_native, encode_frames
from software_gpu.tests.test_symbolic_wave import fixture, inputs, oracle, room_graph, room_oracle
from software_gpu.graphics.geometry import edge_function
from software_gpu.benchmarks.compare_surface_plans import environment, summarize


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--repeats',type=int,default=15)
    args=parser.parse_args()
    if not 15<=args.repeats<=30:parser.error('15..30 repeats required')
    target=Path(args.output_dir).resolve();target.mkdir(parents=True,exist_ok=True)
    names=['native/symbolic/core.hpp','native/symbolic/main.cpp',
           'software_gpu/research/native_symbolic.py','software_gpu/research/symbolic_wave.py',
           'software_gpu/graphics/geometry.py','software_gpu/tests/test_symbolic_wave.py',
           'software_gpu/tests/fixtures/symbolic-edge.ir.json','tools/benchmark_native_symbolic.py',
           'software_gpu/benchmarks/compare_surface_plans.py']
    def hashes():return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}
    before=hashes();head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    cases=[];builds=[]
    for family,shape in [('edge',(2,2,3)),('edge',(16,16)),('edge',(64,64)),('edge',(256,256)),('rooms-32',(1,))]:
        label=family+'-'+'x'.join(map(str,shape))
        ir=fixture(shape) if family=='edge' else room_graph()
        exe,build=build_native(ir,target/label);builds.append({'case':label,**build})
        for scenario in ('static','one-input','all-inputs'):
            a=inputs(ir,991);b={k:v.copy() for k,v in a.items()}
            if scenario=='one-input':b['px' if family=='edge' else 'x0'].flat[0]+=np.float32(.0625)
            if scenario=='all-inputs':b={k:v+np.float32(.0625) for k,v in b.items()}
            frames=[a,b];payload=encode_frames(ir,frames)
            expected=[oracle(v) if family=='edge' else room_oracle(v) for v in frames]
            # Independent numerical comparison precedes every performance claim.
            for mode in ('fused','incremental','direct'):
                result=subprocess.run([str(exe),'run',mode],input=payload,capture_output=True,check=True,timeout=30)
                actual=json.loads(result.stdout)['frames']
                assert len(actual)==2
                for k in range(2):
                    assert actual[k]['status']=='PASS'
                    assert actual[k]['bits']==[expected[k].view(np.uint32).ravel().tolist()]
            loops=100 if int(np.prod(shape))<=4096 else 10
            started=time.perf_counter_ns()
            result=subprocess.run([str(exe),'bench',str(args.repeats),str(loops)],input=payload,
                                  capture_output=True,check=True,timeout=120)
            process_ms=(time.perf_counter_ns()-started)/1e6
            native=json.loads(result.stdout)
            result_bits=native.pop('result_bits')
            assert result_bits==[expected[0].view(np.uint32).ravel().tolist()]
            expected_nodes=0 if scenario=='static' else (3 if family=='edge' else 6) if scenario=='one-input' else (7 if family=='edge' else 63)
            assert native['last_incremental_executed_nodes']==expected_nodes
            # Same resident input pairs, same f32 operations. Python timings are
            # adjacent batches, not falsely labelled as interleaved native pairs.
            if family=='edge':
                prepared=[tuple(np.stack((v[x],v[y])) for x,y in (('ax','ay'),('bx','by'),('px','py'))) for v in frames]
                def reference(i):return edge_function(*prepared[i])
            else:
                def reference(i):return room_oracle(frames[i])
            python_ns=[]
            for repeat in range(-1,args.repeats):
                start=time.perf_counter_ns()
                for i in range(loops*2):value=reference((i+1)%2)
                elapsed=(time.perf_counter_ns()-start)/(loops*2)
                assert value.tobytes()==expected[0].tobytes()
                if repeat>=0:python_ns.append(elapsed)
            samples={**native['samples_ns'],'numpy-reference':python_ns}
            stats={name:summarize(values) for name,values in samples.items()}
            cases.append({'family':family,'shape':shape,'scenario':scenario,'seed':991,
                          'native':native,'stats_ns':stats,'numpy_samples_ns':python_ns,
                          'speedup_ratio_of_medians':{name:statistics.median(python_ns)/statistics.median(values)
                              for name,values in native['samples_ns'].items()},
                          'native_paired_speedup_vs_fused_checked':summarize([
                              old/new for old,new in zip(native['samples_ns']['fused-checked'],
                                                         native['samples_ns']['direct-checked'])]),
                          'native_process_wall_ms_including_protocol_and_all_repeats':process_ms,
                          'wire_sha256':hashlib.sha256(payload).hexdigest(),
                          'output_sha256':[hashlib.sha256(v.tobytes()).hexdigest() for v in expected],
                          'parity':'all-output-f32-bits-identical'})
            print(json.dumps({'case':label,'scenario':scenario,'speedup':cases[-1]['speedup_ratio_of_medians']}),flush=True)
    after=hashes();assert before==after
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==head
    report={'protocol':'are.native-symbolic-comparison.v1','status':'PASS','git_head':head,
            'source_sha256':before,'source_after_sha256':after,'builds':builds,'cases':cases,
            'environment':environment(),'repeats':args.repeats,'workers':1,
            'measurement':'C++ steady_clock batches; no Python calls inside native sample loops; NumPy adjacent independent batches',
            'scopes':{'fused-kernel':'prevalidated inputs, preallocated outputs, intermediate finite checks; full recompute',
                      'fused-checked':'size/environment checks + exact content scan + changed input finite checks/copies + fused kernel + transactional output commit',
                      'incremental-checked':'same input checks/scan + dirty propagation + only changed nodes + transactional buffer swaps',
                      'direct-checked':'synchronous borrowed inputs; size/environment + every input/intermediate finite check in arithmetic pass + owned transactional outputs; no change scan/copies',
                      'numpy-reference':'preassembled inputs, direct edge or fixed pairwise room operations, allocates outputs'},
            'limitations':['one host; no render FPS or GPU comparison','startup, protocol parsing and compilation excluded from per-frame kernel times',
                           'no input-transport comparison','native output is owned read-only memory until next successful frame; NumPy allocates output',
                           'repeat samples average repeated frames; NumPy ratio of medians is not paired; native paired ratio uses rotated batches within each repeat',
                           'IR/generation remain offline Python tools; runtime is C++ only']}
    (target/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
