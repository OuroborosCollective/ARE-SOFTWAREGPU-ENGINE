"""Real full-draw CPU comparison: tiles, batch-first, opt-in C++ raster.

Build is outside timing; preparation, clipping, packing and one native call
are inside. No animation, GPU, Android or Vulkan performance is measured.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time

import numpy as np

from .compare_surface_plans import SCENES, build_scene, environment, summarize
from ..graphics.batch_shader import VertexColorShader
from ..graphics.framebuffer import Framebuffer
from ..graphics.native_raster import NativeRasterKernel, build_raster_kernel
from ..graphics.rasterizer import SoftwareRasterizer
from ..graphics.surface_plan import BATCH_FIRST_POLICY

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ('native/raster/core.hpp', 'native/raster/library.cpp', 'native/symbolic/core.hpp',
           'software_gpu/graphics/native_raster.py', 'software_gpu/graphics/rasterizer.py',
           'software_gpu/graphics/geometry.py', 'software_gpu/graphics/tile_backend.py',
           'software_gpu/graphics/framebuffer.py', 'software_gpu/graphics/batch_shader.py',
           'software_gpu/graphics/surface_plan.py', 'software_gpu/graphics/shader.py',
           'software_gpu/benchmarks/compare_native_raster.py', 'software_gpu/benchmarks/compare_surface_plans.py',
           'software_gpu/benchmarks/compare_tile_backends.py',
           'software_gpu/integrations/aurion/offline_render_worker.py', 'software_gpu/research/native_symbolic.py')
MODES = ('tiles', 'batch-first', 'native-cpp')
SCENES_NATIVE = (*SCENES, ('procedural13k', {'kind':'procedural','seed':991,'rings':64,'segments':104}))


def measure(name, spec, pixels, repeats, kernel, deadline):
    mesh, faces = build_scene(spec)
    engines, samples = {}, {mode: [] for mode in MODES}
    reference = None
    checked = 0
    try:
        for mode in MODES:
            fb = Framebuffer(pixels,pixels)
            engines[mode] = SoftwareRasterizer(fb, num_threads=1,
                backend='tiles-plan' if mode=='batch-first' else mode,
                native_kernel=kernel if mode=='native-cpp' else None,
                plan_policy=BATCH_FIRST_POLICY if mode=='batch-first' else None)
        for repeat in range(-1,repeats):
            offset = max(0,repeat)%len(MODES)
            for mode in MODES[offset:]+MODES[:offset]:
                if time.monotonic() >= deadline:
                    raise RuntimeError('NATIVE_RASTER_BENCHMARK_BUDGET_EXCEEDED')
                engine = engines[mode];engine.fb.clear()
                shader = VertexColorShader()
                start = time.perf_counter_ns()
                engine.draw_mesh(mesh,faces,shader)
                elapsed = (time.perf_counter_ns()-start)/1e6
                actual = (engine.fb.color_buffer.tobytes(),engine.fb.depth_buffer.tobytes())
                if reference is None: reference = actual
                if actual != reference:
                    raise AssertionError('NATIVE_RASTER_BYTE_MISMATCH:'+name+':'+mode)
                checked += 1
                if repeat>=0: samples[mode].append(elapsed)
        return {'scene':name,'scene_spec':spec,'pixels':pixels,'submitted_triangles':len(faces),
                'warmups_per_mode':1,'verified_draws':checked,
                'color_sha256':hashlib.sha256(reference[0]).hexdigest(),
                'depth_sha256':hashlib.sha256(reference[1]).hexdigest(),
                'combined_sha256':hashlib.sha256(b''.join(reference)).hexdigest(),
                'native_receipt':engines['native-cpp'].last_native_receipt,
                'modes':{mode:{'samples_ms':samples[mode],'stats_ms':summarize(samples[mode])} for mode in MODES},
                'native_speedup_paired':{mode:summarize([a/b for a,b in zip(samples[mode],samples['native-cpp'])])
                                         for mode in MODES[:-1]}}
    finally:
        for engine in engines.values():engine.executor.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--pixels',type=int,nargs='+',default=[256])
    parser.add_argument('--repeats',type=int,default=15)
    parser.add_argument('--max-seconds',type=float,default=1800)
    args = parser.parse_args()
    if (not 15<=args.repeats<=30 or any(not 1<=p<=1024 for p in args.pixels) or
            len(args.pixels)>4 or not np.isfinite(args.max_seconds) or args.max_seconds<=0):
        parser.error('require 15..30 repeats, 1..4 sizes within 1..1024, positive finite budget')
    out = Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    hashes = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}
    binary, build = build_raster_kernel(out/'build')
    kernel = NativeRasterKernel(binary,build['binary_sha256'])
    data = {'protocol':'are.native-raster-benchmark.v1','timing_scope':'whole draw_mesh; excludes clear/build/byte check',
            'python_preparation':True,'python_pixel_loop':False,'workers':1,
            'python':platform.python_version(),'numpy':np.__version__,'environment':environment(),
            'source_sha256':hashes,'build':build,'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'rows':[]}
    deadline = time.monotonic()+args.max_seconds
    for pixels in args.pixels:
        for name, spec in SCENES_NATIVE:
            row = measure(name,spec,pixels,args.repeats,kernel,deadline)
            data['rows'].append(row)
            print(json.dumps({'scene':name,'pixels':pixels,'ms':{m:v['stats_ms']['median'] for m,v in row['modes'].items()}}),flush=True)
    if hashes != {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}:
        raise RuntimeError('NATIVE_RASTER_SOURCES_CHANGED_DURING_MEASUREMENT')
    (out/'native-raster-benchmark.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':main()
