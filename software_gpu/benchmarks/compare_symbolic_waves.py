"""Bounded real DAG microbenchmark; no full-frame or GPU performance claim."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--repeats', type=int, default=15)
    args = parser.parse_args()
    if not 15 <= args.repeats <= 30:
        parser.error('15..30 repeats required')
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))
    import numpy as np
    from software_gpu.graphics.geometry import edge_function
    from software_gpu.research.symbolic_wave import WaveRuntime, compiled_python
    from software_gpu.tests.test_symbolic_wave import fixture, inputs, room_graph, room_oracle
    from software_gpu.benchmarks.compare_surface_plans import environment, summarize
    def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    declared = ['software_gpu/research/symbolic_wave.py',
                'software_gpu/research/symbolic-edge.wl',
                'software_gpu/research/parse-symbolic-edge.wl',
                'software_gpu/research/room-map-probe.wl',
                'software_gpu/tests/fixtures/symbolic-edge.ir.json',
                'software_gpu/tests/test_symbolic_wave.py',
                'software_gpu/graphics/geometry.py',
                'software_gpu/benchmarks/compare_symbolic_waves.py',
                'software_gpu/benchmarks/compare_surface_plans.py',
                'tools/coverage_gate.py']
    sources = {name: digest(root/name) for name in declared}
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    cases = []
    modes = ('reference', 'generated-python', 'wave-runtime')
    families = [('edge', shape) for shape in ((2,2,3), (16,16), (64,64), (256,256))]
    families += [('rooms-32', (1,))]
    for family, shape in families:
        for scenario in ('static', 'one-input', 'all-inputs'):
            ir = fixture(shape) if family == 'edge' else room_graph()
            runtime, generated = WaveRuntime(ir), compiled_python(ir)
            data = inputs(ir, 991)
            output = ir['outputs'][0]
            timings = {mode: [] for mode in modes}
            receipts, hashes = [], []
            def prepare():
                if family == 'edge':
                    a = np.stack((data['ax'], data['ay']))
                    b = np.stack((data['bx'], data['by']))
                    p = np.stack((data['px'], data['py']))
                    return lambda: edge_function(a,b,p)
                return lambda: room_oracle(data)
            reference = prepare()
            expected = reference().tobytes()
            assert generated(data)[output].tobytes() == expected
            assert runtime.evaluate(data)[output].tobytes() == expected
            for repeat in range(args.repeats):
                if scenario == 'one-input':
                    data['px' if family == 'edge' else 'x0'].flat[0] += np.float32(.0625)
                elif scenario == 'all-inputs':
                    for value in data.values(): value += np.float32(.0625)
                reference = prepare()  # Input assembly is outside all measured kernels.
                values = {}
                order = modes[repeat % 3:] + modes[:repeat % 3]
                for mode in order:
                    call = (reference if mode == 'reference' else
                            (lambda: generated(data)[output]) if mode == 'generated-python' else
                            (lambda: runtime.evaluate(data)[output]))
                    start = time.perf_counter_ns()
                    result = call()
                    elapsed_ms = (time.perf_counter_ns() - start) / 1e6
                    timings[mode].append(elapsed_ms)
                    values[mode] = result.tobytes()
                    if mode == 'wave-runtime': receipts.append(copy.deepcopy(runtime.last_receipt))
                assert len(set(values.values())) == 1, (family, shape, scenario, repeat)
                expected_nodes = (0 if scenario == 'static' else
                                  (3 if family == 'edge' else 6) if scenario == 'one-input' else
                                  (7 if family == 'edge' else 63))
                assert len(runtime.last_receipt['executed_nodes']) == expected_nodes
                hashes.append(hashlib.sha256(values['reference']).hexdigest())
            paired = {mode: summarize([base/actual for base,actual in
                       zip(timings['reference'],timings[mode])]) for mode in modes[1:]}
            cases.append({'family': family, 'tensor_shape': list(shape), 'scenario': scenario,
                          'graph_nodes': len(ir['nodes']), 'seed': 991, 'parity': 'byte-identical',
                          'raw_ms': timings, 'stats_ms': {k:summarize(v) for k,v in timings.items()},
                          'speedup_paired': paired, 'frame_sha256': hashes, 'receipts': receipts})
    sources_after = {name: digest(root/name) for name in declared}
    head_after = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,text=True).strip()
    assert head == head_after and sources == sources_after
    report = {'protocol':'are.symbolic-wave-benchmark.v1', 'status':'PASS',
              'git_head':head, 'git_head_after':head_after,
              'source_sha256':sources, 'source_after_sha256':sources_after,
              'benchmark_script_sha256':digest(Path(__file__)),
              'repeats':args.repeats, 'warmups_per_case':1, 'workers':1,
              'measured_evaluations':len(cases)*len(modes)*args.repeats,
              'environment':{**environment(),'python':platform.python_version(), 'numpy':np.__version__},
              'baseline_scope':'edge_function on preassembled inputs; rooms use fixed Python pairwise f32 operations',
              'candidate_scope':'generated checked NumPy code; runtime includes full input hashing, validation, immutable cache and receipts',
              'limitations':['microkernels only, no renderer FPS', 'no parallel worker execution',
                             'single host, no Gaming-GPU comparison', 'colors/coordinates are metadata',
                             'original Wolfram Sin/Cos are not operators in this bounded f32 DSL'],
              'cases':cases}
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':'PASS','cases':len(cases),'measured_evaluations':report['measured_evaluations'],
                      'paired_medians':[{'family':c['family'],'shape':c['tensor_shape'],'scenario':c['scenario'],
                           **{k:round(v['median'],3) for k,v in c['speedup_paired'].items()}} for c in cases]}))

if __name__ == '__main__': main()
