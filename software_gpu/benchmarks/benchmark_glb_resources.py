"""Isolated BIN-slicing allocation A/B, NOT total GLB import / full frame / export.

The unchanged GLB2 preflight remains the single container authority. Only the
known copying expression from an existing offline LOD loader is compared to a
memoryview expression; valid generated GLB bytes are inspected separately.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import gc
import os
from pathlib import Path
import platform
import statistics
import struct
import subprocess
import time
import tracemalloc
from software_gpu.tests.fixtures.glb_resource_fixture import make_resource_glb
from tools.glb_container_preflight import inspect_glb

REPEATS=15
MESHES=(1,100,1300,3500)

def summary(values):
    ordered=sorted(values)
    def percentile(q):
        idx=(len(ordered)-1)*q
        lo=int(idx)
        return ordered[lo]+(ordered[min(lo+1,len(ordered)-1)]-ordered[lo])*(idx-lo)
    med=statistics.median(values)
    return {'n':len(values),'median':med,'p95':percentile(.95),
            'iqr':percentile(.75)-percentile(.25),
            'mad':statistics.median(abs(v-med) for v in values),
            'min':ordered[0],'max':ordered[-1]}

def chunk_bounds(raw):
    # Metadata is admitted by the unchanged production GLB2 preflight first.
    inspect_glb(raw)
    json_len,kind=struct.unpack_from('<II',raw,12)
    if kind != 0x4E4F534A:
        raise ValueError('GLB_RESOURCE_JSON_CHUNK')
    start=20+json_len
    size,kind=struct.unpack_from('<II',raw,start)
    if kind != 0x004E4942 or size>len(raw)-start-8:
        raise ValueError('GLB_RESOURCE_BIN_CHUNK')
    return start+8,start+8+size

def measure(raw):
    begin,end=chunk_bounds(raw)
    samples={label:[] for label in ('historical_bin_slice','memoryview_bin_slice')}
    allocations={label:[] for label in samples}
    for repeat in range(REPEATS+1):
        order=list(samples)
        if repeat%2:order.reverse()
        for label in order:
            gc.collect()
            tracemalloc.start()
            baseline=tracemalloc.get_traced_memory()[0]
            begin_ns=time.perf_counter_ns()
            if label=='historical_bin_slice':
                result=raw[begin:end]
            else:
                result=memoryview(raw)[begin:end]
            ms=(time.perf_counter_ns()-begin_ns)/1e6
            _,peak=tracemalloc.get_traced_memory()
            if len(result)!=end-begin or result[:8]!=raw[begin:begin+8]:
                raise AssertionError('GLB_RESOURCE_BIN_SLICE_MISMATCH')
            if repeat:
                samples[label].append(ms)
                allocations[label].append(max(0,peak-baseline))
            del result
            tracemalloc.stop()
    paired=[a/b for a,b in zip(samples['historical_bin_slice'],samples['memoryview_bin_slice'])]
    return {'samples_ms':samples,'peak_traced_allocation_bytes':allocations,
            'statistics_ms':{name:summary(row) for name,row in samples.items()},
            'statistics_alloc_bytes':{name:summary(row) for name,row in allocations.items()},
            'paired_speed_ratio':summary(paired),'semantic_results_identical':True}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--bin-bytes',type=int,default=4<<20)
    a=p.parse_args(argv)
    if a.bin_bytes < 44 or a.bin_bytes>(16<<20) or a.bin_bytes%4:
        p.error('bin-bytes must be 44..16777216 and aligned to four')
    from software_gpu.tests.fixtures import glb_resource_fixture
    from software_gpu.integrations.aurion import offline_lod_worker
    from tools import glb_container_preflight
    root=Path(__file__).resolve().parents[2]
    sources=[Path(__file__).resolve(),Path(glb_resource_fixture.__file__).resolve(),
             Path(glb_container_preflight.__file__).resolve(),Path(offline_lod_worker.__file__).resolve()]
    rows=[]
    for count in MESHES:
        raw=make_resource_glb(count,bin_bytes=a.bin_bytes)
        rows.append({'mesh_count':count,'input_bytes':len(raw),'asset_sha256':hashlib.sha256(raw).hexdigest(),
                     'asset_class':'generated_valid_glb2_fixture_not_independent_asset',
                     'results':measure(raw)})
    result={'protocol':'are.glb-resource-microbenchmark.v2',
            'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
            'repeats':REPEATS,'bench_scope':'bin_slice_expression_only',
            'full_frame_benchmarked':False,'native_multi_mesh_import_supported':False,
            'export_benchmarked':False,'automatic_activation':False,
            'cpu':platform.processor() or platform.machine(), 'python':platform.python_version(),
            'affinity_cpus':sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,
            'source_paths_sha256':{str(x.relative_to(root)):hashlib.sha256(x.read_bytes()).hexdigest() for x in sources},
            'rows':rows}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print('GLB_RESOURCE_MICROBENCHMARK_OK',len(rows),REPEATS)
if __name__=='__main__':main()