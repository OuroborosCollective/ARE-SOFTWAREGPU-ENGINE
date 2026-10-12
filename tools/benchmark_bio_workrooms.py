#!/usr/bin/env python3
"""Bounded paired native ablation: original C++17 core versus four bio principles."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from software_gpu.research.bio_workrooms import (BASELINE_COMMIT, POLICIES,
    build_bio_workrooms, run_bio_workrooms)
from software_gpu.research.workrooms import descriptor, encode_request
from software_gpu.tests.test_workrooms import renderer_oracle, scene_fixture
from software_gpu.tests.test_bio_workrooms import sparse_scene

SOURCES = ('native/symbolic/core.hpp','native/symbolic/workrooms.hpp',
    'native/symbolic/workrooms_wire.hpp','native/symbolic/workrooms_main.cpp',
    'native/symbolic/bio_workrooms.hpp','native/symbolic/bio_workrooms_main.cpp',
    'software_gpu/research/workrooms.py','software_gpu/research/workrooms.wl',
    'software_gpu/research/bio_workrooms.py','software_gpu/research/bio_workrooms.wl','software_gpu/tests/test_workrooms.py',
    'software_gpu/tests/test_bio_workrooms.py','software_gpu/tests/fixtures/bio_checkpoint_probe.cpp',
    'software_gpu/tests/fixtures/workrooms-baseline-87ff.hpp',
    'software_gpu/graphics/geometry.py','software_gpu/graphics/postprocess.py',
    'tools/benchmark_bio_workrooms.py')


def stats(data):
    ordered = sorted(data)
    def percentile(q):
        i = (len(ordered)-1)*q
        lo = int(i)
        return ordered[lo]+(ordered[min(lo+1,len(ordered)-1)]-ordered[lo])*(i-lo)
    median = statistics.median(data)
    return dict(n=len(data),median=median,iqr=percentile(.75)-percentile(.25),
                mad=statistics.median(abs(v-median) for v in data),
                min=min(data),max=max(data),p95=percentile(.95))


def source_hashes():
    return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}


def environment():
    model = None
    path = Path('/proc/cpuinfo')
    if path.exists():
        model = next((line.split(':',1)[1].strip() for line in path.read_text().splitlines()
                      if line.startswith('model name')),None)
    bounds = {}
    for filename in ('cpu.max','memory.max'):
        p = Path('/sys/fs/cgroup')/filename
        if p.exists():bounds[filename] = p.read_text().strip()
    return dict(platform=platform.platform(),python=platform.python_version(),machine=platform.machine(),
                cpu_model=model,logical_cpu_count=os.cpu_count(),
                available_cpu_affinity=sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,
                cgroup_limits=bounds,thermal_measurements=None,
                thread_environment={k:os.environ.get(k) for k in
                    ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--repeats',type=int,default=15)
    parser.add_argument('--max-seconds',type=float,default=600)
    args = parser.parse_args()
    if not 15<=args.repeats<=30 or not math.isfinite(args.max_seconds) or not 0<args.max_seconds<=1800:
        parser.error('15..30 repeats and a finite budget <=1800 seconds required')
    target = Path(args.output_dir).resolve();target.mkdir(parents=True,exist_ok=True)
    start = time.monotonic();before = source_hashes()
    exe,build = build_bio_workrooms(target/'native')
    cases = [];images = {}
    workloads = [('large4',scene_fixture(),1),('large4',scene_fixture(),16),
                 ('sparse64',sparse_scene(),16)]
    # Independent existing Python renderer at small resolution; full native
    # buffers compare against frozen original code on EVERY timed large frame.
    oracle_results = []
    for name,scene in [('large4',scene_fixture()),('sparse64',sparse_scene())]:
        ref,final = renderer_oracle(31,29,scene)
        out = run_bio_workrooms(exe,descriptor(31,29,4),scene,4,2,'combined')
        assert out['resolved']==ref.color_buffer.tobytes()
        assert out['rgba']==final.color_buffer.tobytes()
        assert out['depth']==final.depth_buffer.astype('<f4').tobytes()
        oracle_results.append(dict(scene=name,width=31,height=29,
            rgba_depth_and_resolved_exact=True,rgba_sha256=out['receipt']['rgba_sha256']))
    for workload,(name,scene,tile) in enumerate(workloads):
        # Rotate the mode order between workloads; each process alternates
        # baseline/candidate frames, same geometry, flags and worker count.
        modes = list(POLICIES[workload:]+POLICIES[:workload])
        for workers,mode in [(4,m) for m in modes]+([(1,'combined')] if tile==16 else []):
            if time.monotonic()-start>args.max_seconds:raise RuntimeError('BIO_BENCHMARK_BUDGET_EXHAUSTED')
            ir = descriptor(640,640,tile)
            request = encode_request(ir,scene)
            (target/f'{name}-tile{tile}.request.bin').write_bytes(request)
            process_start = time.perf_counter_ns()
            out = run_bio_workrooms(exe,ir,scene,workers,args.repeats,mode)
            process_ms = (time.perf_counter_ns()-process_start)/1e6
            receipt = out['receipt']
            digest = hashlib.sha256(b''.join(out[k] for k in ('resolved','rgba','depth'))).hexdigest()
            images.setdefault(name,digest);assert images[name]==digest
            baseline = stats(receipt['baseline_samples_ms']);candidate = stats(receipt['samples_ms'])
            paired = stats([b/c for b,c in zip(receipt['baseline_samples_ms'],receipt['samples_ms'])])
            case = dict(scene=name,width=640,height=640,tile=tile,triangles=len(scene),workers=workers,
                policy=mode,baseline_ms=baseline,candidate_ms=candidate,
                baseline_cpu_ms=stats(receipt['baseline_cpu_samples_ms']),
                candidate_cpu_ms=stats(receipt['cpu_samples_ms']),
                speedup_ratio_of_medians=baseline['median']/candidate['median'],
                speedup_paired=paired,all_buffers_sha256=digest,full_buffer_parity_every_frame=True,
                process_ms_including_startup_allocations_oracle_warmups_all_pairs_and_serialization=process_ms,
                native=receipt)
            cases.append(case)
            print(json.dumps({k:case[k] for k in ('scene','tile','workers','policy','speedup_ratio_of_medians')}|
                             dict(baseline_ms=baseline['median'],candidate_ms=candidate['median'])),flush=True)
            if mode=='combined' and workers==4 and tile==16:
                import numpy as np
                rgb = np.frombuffer(out['rgba'],dtype=np.uint8).reshape(640,640,4)[...,:3].tobytes()
                (target/f'{name}.ppm').write_bytes(b'P6\n640 640\n255\n'+rgb)
    after = source_hashes();assert before==after
    report = dict(protocol='are.bio-workrooms.benchmark.v1',status='PASS',
        baseline_commit=BASELINE_COMMIT,build=build,
        checkout_head_at_measurement=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_sha256=before,source_after_sha256=after,environment=environment(),
        repeats=args.repeats,total_seconds=time.monotonic()-start,
        metric='resident native frame elapsed time',unit='ms',statistic='median',direction='lower',
        oracle=oracle_results,cases=cases,
        timing_contract=dict(included=['all native rendering','spatial bins rebuilt each frame',
            'scheduling and dependency publication','native worker synchronization','checkpoint/handoff verification'],
            excluded=['process startup','binary parsing','initial buffer allocation and resident worker creation',
                      'full-buffer parity comparison','response serialization','Python transport'],
            construction='measured separately for each baseline and candidate; not part of frame speed ratio',
            frontier_stage_ms='one shared overlapping interval, do not sum stages 1..3'),
        limitations=['CPU versus CPU on one host, no hardware GPU or game FPS comparison',
            'Small fixed flat-shaded already-clipped scenes, 4x MSAA and existing FXAA; not arbitrary games',
            'Four principles are implementation hypotheses, not biological simulation or imported biological code',
            'Ratios describe these runs; no guaranteed factor and no additive/multiplicative combination assumption',
            'No temperature, energy or thermal safety measurements',
            'Checkpoint overhead may make combined slower; all regressions retained',
            'Only one bounded fixed candidate; no performance-driven tuning after measurement'])
    (target/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
