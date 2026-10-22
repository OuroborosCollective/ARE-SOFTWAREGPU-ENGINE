"""Source-bound whole-draw comparison of the three reviewed band candidates.

Run serially with OMP/BLAS threads=1; pin affinity before invocation if available.
Historical variants are read only from the exact reviewed local Git commits.
Each round rotates/reverses order; clear is outside timing; complete draw_mesh is
inside timing. Every draw's full RGBA8/depth bytes are checked, without tolerance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time
import numpy as np
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.tests.test_band_inline_parity import ReferenceRasterizer, scenes, render
from software_gpu.benchmarks.compare_tile_backends import make_fixture, FlatShader

ROOT=Path(__file__).resolve().parents[2]
REVISIONS={
    'main':'048d794ba563f64af317cd216061d3a85d9cbafa',
    'pr154':'c938a4eb099c8b9afc7ebcba09a6d77e6370329c',
    'pr155':'28f85a7bf2640c0d2e09b36ccb6c778d3bb462a8',
    'pr156':'bf182361874bbfae529168e3a954a26978cc576a',
}

def digest(data): return hashlib.sha256(data).hexdigest()

def variants():
    result={}; hashes={}
    for label,sha in REVISIONS.items():
        source=subprocess.check_output(['git','show',sha+':software_gpu/graphics/rasterizer.py'],cwd=ROOT)
        namespace={'__name__':'software_gpu.graphics._review_'+label,'__package__':'software_gpu.graphics'}
        exec(compile(source,sha+':rasterizer.py','exec'),namespace)
        result[label]=namespace['SoftwareRasterizer']; hashes[label]=digest(source)
    result['candidate']=SoftwareRasterizer
    hashes['candidate']=digest((ROOT/'software_gpu/graphics/rasterizer.py').read_bytes())
    return result,hashes

def stats(values):
    median=statistics.median(values)
    return {'median':median,'iqr':float(np.percentile(values,75)-np.percentile(values,25)),
            'mad':statistics.median(abs(x-median) for x in values),'min':min(values),'max':max(values),'n':len(values)}

def buffers(fb): return fb.color_buffer.tobytes(),fb.depth_buffer.tobytes()

def differences(a,b):
    return {'rgba8_changed_bytes':sum(x!=y for x,y in zip(a[0],b[0])),
            'depth_changed_values':int(np.count_nonzero(np.frombuffer(a[1],np.uint32)!=np.frombuffer(b[1],np.uint32)))}

def differential(classes):
    report=[]
    for name,vertices,faces in scenes():
        for width,height,workers in ((32,32,1),(37,19,3),(1,1,1)):
            baseline=buffers(render(ReferenceRasterizer,vertices,faces,width,height,workers))
            row={'scene':name,'size':[width,height],'workers':workers,'variants':{}}
            for label,cls in classes.items():
                output=buffers(render(cls,vertices,faces,width,height,workers))
                row['variants'][label]={'byte_identical':output==baseline,**differences(baseline,output)}
            report.append(row)
    return report

def measure(classes,size,count,radius,repeats):
    vertices,faces=make_fixture(count,radius);shader=FlatShader()
    engines={k:cls(Framebuffer(size,size),backend='bands',num_threads=1) for k,cls in classes.items()}
    samples={k:[] for k in classes}; parity={k:True for k in classes}; orders=[]; hashes={}
    reference=None
    try:
        for round_index in range(-1,repeats):
            labels=list(classes)
            if round_index>=0:
                shift=round_index%len(labels);labels=labels[shift:]+labels[:shift]
                if round_index%2: labels.reverse()
                orders.append(labels)
            for label in labels:
                engine=engines[label]; engine.fb.clear(0,0,0,255,1.)
                start=time.perf_counter_ns();engine.draw_mesh(vertices,faces,shader)
                elapsed=(time.perf_counter_ns()-start)/1e6
                output=buffers(engine.fb)
                if reference is None: reference=output
                parity[label] &= output==reference
                hashes[label]={'rgba8':digest(output[0]),'depth':digest(output[1])}
                if round_index>=0: samples[label].append(elapsed)
    finally:
        for engine in engines.values(): engine.executor.shutdown(wait=True)
    return {'size':size,'triangles':count,'radius':radius,'repeats':repeats,'order':orders,
            'samples_ms':samples,'stats_ms':{k:stats(v) for k,v in samples.items()},
            'speedup_paired':{k:stats([a/b for a,b in zip(samples['main'],v)]) for k,v in samples.items()},
            'byte_identical':parity,'buffer_sha256':hashes}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    p.add_argument('--repeats',type=int,default=15);p.add_argument('--differential-only',action='store_true')
    args=p.parse_args()
    if not 1<=args.repeats<=30: p.error('repeats must be 1..30')
    classes,hashes=variants()
    cpu=platform.processor()
    if Path('/proc/cpuinfo').exists():
        cpu=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),cpu)
    report={'protocol':'are.band-inline-comparison.v1','revisions':REVISIONS,'rasterizer_sha256':hashes,
            'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),
            'python':platform.python_version(),'numpy':np.__version__,'platform':platform.platform(),'cpu':cpu,
            'affinity':sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,
            'threads':{k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')},
            'seed':1234,'workers':1,'scope':'full draw_mesh, warmed, fresh buffers; CPU only',
            'source_sha256':{str(f.relative_to(ROOT)):digest(f.read_bytes()) for f in [*sorted((ROOT/'software_gpu/graphics').glob('*.py')),Path(__file__),ROOT/'software_gpu/tests/test_band_inline_parity.py',ROOT/'software_gpu/tests/fixtures/band_reference.py',ROOT/'software_gpu/benchmarks/compare_tile_backends.py',ROOT/'software_gpu/tests/test_raster_correctness_contract.py']},
            'differential':differential(classes),'results':[]}
    if not args.differential_only:
        for case in ((128,160,.05),(128,8,.8),(256,320,.045)):
            report['results'].append(measure(classes,*case,args.repeats))
    report['receipt_sha256']=digest(json.dumps(report,sort_keys=True,separators=(',',':')).encode())
    Path(args.output).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'numpy':np.__version__,'mismatching_cases':{k:sum(not r['variants'][k]['byte_identical'] for r in report['differential']) for k in classes},'speedups':[{k:v['median'] for k,v in r['speedup_paired'].items()} for r in report['results']]}))
    if any(not r['variants']['candidate']['byte_identical'] for r in report['differential']) or any(not r['byte_identical']['candidate'] for r in report['results']):
        raise SystemExit('candidate parity regression')

if __name__=='__main__': main()
