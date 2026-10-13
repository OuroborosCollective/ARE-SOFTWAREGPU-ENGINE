#!/usr/bin/env python3
"""Opt-in, bounded, serial C++17 tile-frontier cache/memory-order ablation."""
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from software_gpu.research.bio_workrooms import ABLATIONS,build_bio_workrooms,run_bio_workrooms
from software_gpu.research.workrooms import descriptor,encode_request
from software_gpu.tests.test_bio_workrooms import sparse_scene
from software_gpu.tests.test_workrooms import scene_fixture


def stats(samples):
    median=statistics.median(samples)
    ordered=sorted(samples)
    def q(f):
        x=(len(ordered)-1)*f;lo=int(x)
        return ordered[lo]+(ordered[min(lo+1,len(ordered)-1)]-ordered[lo])*(x-lo)
    return dict(n=len(samples),median_ms=median,iqr_ms=q(.75)-q(.25),
                mad_ms=statistics.median(abs(t-median) for t in samples),
                samples_ms=samples)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',required=True)
    p.add_argument('--repeats',type=int,default=15)
    p.add_argument('--max-seconds',type=float,default=1200)
    p.add_argument('--workers',nargs='+',type=int,default=[1,2,4,8])
    p.add_argument('--variants',nargs='+',choices=tuple(ABLATIONS),default=list(ABLATIONS))
    a=p.parse_args()
    if not (15<=a.repeats<=30 and math.isfinite(a.max_seconds) and 0<a.max_seconds<=1800
            and a.workers and len(set(a.workers))==len(a.workers)
            and all(w in (1,2,4,8) for w in a.workers)
            and len(set(a.variants))==len(a.variants)):
        p.error('repeats 15..30, bounded seconds <=1800, unique workers in 1/2/4/8')
    out=Path(a.output_dir).resolve()
    out.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    sources=['native/symbolic/bio_workrooms.hpp','native/symbolic/bio_workrooms_main.cpp',
             'software_gpu/research/bio_workrooms.py','tools/benchmark_frontier_cache.py']
    source_sha={s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources}
    cases=[('sparse64-tile1',128,1,sparse_scene()),
           ('large4-tile16',256,16,scene_fixture())]
    report=dict(protocol='are.bio-frontier.cache-ablation.v1',status='RUNNING',
                head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                source_sha256=source_sha,
                environment=dict(system=platform.platform(),machine=platform.machine(),
                                 logical_cpus=os.cpu_count(),affinity=sorted(os.sched_getaffinity(0))
                                 if hasattr(os,'sched_getaffinity') else None),
                repeats=a.repeats,builds={},cases=[],
                limitations=['CPU-to-CPU only, no GPU/fps claim',
                  'This measures a different scalar scene from the PBR benchmark',
                  'No perf c2c profile in this receipt; cannot infer false sharing causality',
                  'Paired baseline is frozen old renderer, not one cross-variant control',
                  'One host, no energy or temperature proof'])
    all_digests={}
    for variant in a.variants:
        if time.monotonic()-started>a.max_seconds:raise RuntimeError('CACHE_BENCHMARK_BUDGET')
        exe,build=build_bio_workrooms(out/'build'/variant,ablation=variant)
        report['builds'][variant]=build
        for name,pixels,tile,scene in cases:
            wire=encode_request(descriptor(pixels,pixels,tile),scene)
            (out/f'{name}.request.bin').write_bytes(wire)
            for workers in a.workers:
                if time.monotonic()-started>a.max_seconds:raise RuntimeError('CACHE_BENCHMARK_BUDGET')
                data=run_bio_workrooms(exe,descriptor(pixels,pixels,tile),scene,
                                       workers,a.repeats,'combined')
                digest=hashlib.sha256(b''.join(data[k] for k in ('resolved','rgba','depth'))).hexdigest()
                if name in all_digests and all_digests[name]!=digest:
                    raise AssertionError('CACHE_VARIANT_OR_WORKER_PARITY')
                all_digests[name]=digest
                receipt=data['receipt']
                baseline=stats(receipt['baseline_samples_ms'])
                candidate=stats(receipt['samples_ms'])
                entry=dict(variant=variant,scene=name,pixels=pixels,tile=tile,
                           triangles=len(scene),workers=workers,
                           request_sha256=hashlib.sha256(wire).hexdigest(),
                           image_depth_sha256=digest,full_frame_parity=True,
                           historical_baseline=baseline,candidate=candidate,
                           ratio_of_medians=baseline['median_ms']/candidate['median_ms'],
                           receipt=receipt)
                report['cases'].append(entry)
                print(json.dumps({k:entry[k] for k in
                    ('variant','scene','workers','ratio_of_medians')}),flush=True)
    if source_sha!={s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources}:
        raise RuntimeError('SOURCE_DRIFT')
    report['status']='PASS'
    report['seconds']=time.monotonic()-started
    (out/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
