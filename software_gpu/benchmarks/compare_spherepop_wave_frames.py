"""Actual whole draw + CAG/SpherePop radial Doppler CPU performance comparison.

No claimed GPU parity. No fake timings. The *same* saved scene is rendered in
three real software backends. For enabled runs the native merged wave executes
on a bound object-owner/depth projection. Compare each backend both with and
without the effect. RGBA+Depth and replay parity are mandatory, not optional.
"""
import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

import numpy as np

from .compare_surface_plans import build_scene, environment, summarize
from ..graphics.batch_shader import VertexColorShader
from ..graphics.framebuffer import Framebuffer
from ..graphics.native_raster import NativeRasterKernel, build_raster_kernel
from ..graphics.rasterizer import SoftwareRasterizer
from ..graphics.surface_plan import BATCH_FIRST_POLICY
from ..research.native_symbolic import FLAGS, compiler

ROOT=Path(__file__).resolve().parents[2]
MODES=("tiles", "batch-first", "native-cpp")
SOURCES=(
    "native/raster/spherepop_wave_benchmark_bridge.cpp",
    "native/raster/spherepop_cag_radial_wave.hpp",
    "native/raster/spherepop_object_mask.hpp",
    "native/raster/spherepop_doppler_profile.hpp",
    "native/raster/core.hpp",
    "native/raster/library.cpp",
    "native/symbolic/core.hpp",
    "software_gpu/benchmarks/compare_spherepop_wave_frames.py",
    "software_gpu/benchmarks/compare_surface_plans.py",
    "software_gpu/benchmarks/compare_tile_backends.py",
    "software_gpu/graphics/native_raster.py",
    "software_gpu/graphics/rasterizer.py",
    "software_gpu/graphics/geometry.py",
    "software_gpu/graphics/tile_backend.py",
    "software_gpu/graphics/framebuffer.py",
    "software_gpu/graphics/batch_shader.py",
    "software_gpu/graphics/surface_plan.py",
    "software_gpu/graphics/shader.py",
    "software_gpu/integrations/aurion/offline_render_worker.py",
    "software_gpu/research/native_symbolic.py",
)
SCENES=(
    ("large-surfaces",{"kind":"fixture","seed":1234,"triangles":8,"size":.8}),
    ("procedural400",{"kind":"procedural","seed":991,"rings":10,"segments":20}),
)

class Metrics(ctypes.Structure):
    _fields_=[("finalized",ctypes.c_uint64),("refused",ctypes.c_uint64),
              ("tinted",ctypes.c_uint64),("fingerprint",ctypes.c_uint64)]

def binary_bridge(directory):
    src=ROOT/"native/raster/spherepop_wave_benchmark_bridge.cpp"
    name="wavebench.dll" if sys.platform=="win32" else "wavebench.so"
    dest=Path(directory)/name
    shared=["-shared","-static"] if sys.platform=="win32" else ["-shared","-fPIC"]
    cmd=[compiler(),*FLAGS,*shared,str(src),"-o",str(dest)]
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
    if r.returncode:raise RuntimeError("SPHEREPOP_BENCHMARK_BUILD_FAILED:"+r.stderr[-5000:])
    digest=hashlib.sha256(dest.read_bytes()).hexdigest()
    lib=ctypes.CDLL(str(dest))
    lib.are_wave_benchmark_abi.argtypes=[]
    lib.are_wave_benchmark_abi.restype=ctypes.c_uint
    if lib.are_wave_benchmark_abi()!=1:
        raise RuntimeError("SPHEREPOP_BENCHMARK_ABI")
    fn=lib.are_wave_benchmark_apply
    ptr=ctypes.c_void_p
    size=ctypes.c_size_t
    fn.argtypes=[ptr,size,ptr,size,ptr,size,ctypes.c_int,ctypes.c_int,
                 ctypes.c_int,ctypes.c_int,ctypes.c_double,ctypes.c_double,
                 ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.POINTER(Metrics)]
    fn.restype=ctypes.c_int
    return fn, {"compiler":cmd[0],"flags":cmd[1:-3],"binary_sha256":digest}

def _digest(color,depth):
    return {"rgba_sha256":hashlib.sha256(color).hexdigest(),
            "depth_sha256":hashlib.sha256(depth).hexdigest()}

def measure_scene(name,spec,pixels,repeats,kernel,wave_fn,deadline):
    mesh, faces=build_scene(spec)
    engines={}
    try:
        for backend in MODES:
            fb=Framebuffer(pixels,pixels)
            engines[backend]=(fb,SoftwareRasterizer(fb,num_threads=1,
                backend="tiles-plan" if backend=="batch-first" else backend,
                plan_policy=BATCH_FIRST_POLICY if backend=="batch-first" else None,
                native_kernel=kernel if backend=="native-cpp" else None))
        samples={k:{"off":[],"on":[]} for k in MODES}
        baseline_hash=None
        effect_hash=None
        fingerprints=set()
        last_metrics=None
        for repeat in range(-1,repeats):
            # AB/BA alternation inside each real backend, rotate across backends.
            mode_order=list(MODES[repeat%3:]+MODES[:repeat%3])
            for mode in mode_order:
                states=("off","on") if repeat%2==0 else ("on","off")
                for state in states:
                    if time.monotonic()>deadline:
                        raise RuntimeError("SPHEREPOP_BENCHMARK_DEADLINE")
                    fb,engine=engines[mode]
                    fb.clear()
                    start=time.perf_counter_ns()
                    engine.draw_mesh(mesh,faces,VertexColorShader())
                    if state=="on":
                        # Owners are derived from final nearest depth; one owner
                        # explicitly labels this independently rendered object.
                        owners=np.zeros((pixels,pixels),dtype=np.uint32)
                        visible=fb.depth_buffer<np.float32(1.0)
                        owners[visible]=7
                        # Existing raster stores signed clip/NDC depth [-1,1].
                        # SpherePop accepts normalized [0,1]. Keep the actual
                        # framebuffer untouched; project a distinct float32
                        # depth input, and INCLUDE its cost in wave-on timing.
                        if not np.isfinite(fb.depth_buffer).all() or np.any(fb.depth_buffer[visible]<-1.0):
                            raise AssertionError("SPHEREPOP_NATIVE_DEPTH_DOMAIN")
                        wave_depth=fb.depth_buffer.copy()
                        wave_depth[visible]=(wave_depth[visible]+np.float32(1.0))*np.float32(0.5)
                        metrics=Metrics()
                        code=wave_fn(fb.color_buffer.ctypes.data,fb.color_buffer.nbytes,
                            wave_depth.ctypes.data,wave_depth.size,
                            owners.ctypes.data,owners.size,pixels,pixels,
                            pixels//2,pixels//2,30.0,0.0,0.0,120.0,1.0,
                            ctypes.byref(metrics))
                        if code!=0:
                            raise RuntimeError("SPHEREPOP_BENCHMARK_WAVE_REJECTED:"+str(code))
                        if metrics.finalized!=pixels*pixels:
                            raise AssertionError("SPHEREPOP_BENCHMARK_AREA_INCOMPLETE")
                        if metrics.refused<=0:
                            raise AssertionError("SPHEREPOP_BENCHMARK_DUPLICATES_NOT_REJECTED")
                        fingerprints.add(metrics.fingerprint)
                        last_metrics={"finalized":metrics.finalized,"refused":metrics.refused,
                                      "tinted":metrics.tinted,"fingerprint":metrics.fingerprint}
                    elapsed=(time.perf_counter_ns()-start)/1e6
                    if not math.isfinite(elapsed) or elapsed<=0:
                        raise RuntimeError("SPHEREPOP_BENCHMARK_CLOCK")
                    hashes=_digest(fb.color_buffer.tobytes(),fb.depth_buffer.tobytes())
                    if state=="off":
                        if baseline_hash is None:baseline_hash=hashes
                        elif baseline_hash!=hashes:raise AssertionError("SPHEREPOP_BASELINE_PARITY")
                    else:
                        if effect_hash is None:effect_hash=hashes
                        elif effect_hash!=hashes:raise AssertionError("SPHEREPOP_EFFECT_PARITY")
                        # An AB/BA pair may execute the effect before the
                        # baseline. Compare final references after both ran.
                    if repeat>=0:samples[mode][state].append(elapsed)
        if baseline_hash is None or effect_hash is None or baseline_hash==effect_hash or len(fingerprints)!=1:
            raise AssertionError("SPHEREPOP_EFFECT_NOT_EXERCISED_OR_NONDETERMINISTIC")
        if baseline_hash["depth_sha256"]!=effect_hash["depth_sha256"]:
            raise AssertionError("SPHEREPOP_DEPTH_CHANGED")
        pairs={}
        for mode in MODES:
            off=samples[mode]["off"]
            on=samples[mode]["on"]
            pairs[mode]={"raster_only":summarize(off),
                         "raster_plus_wave":summarize(on),
                         "effect_cost_ratio_paired":summarize([x/y for x,y in zip(off,on)]),
                         "raw_ms":samples[mode]}
        return {"scene":name,"spec":spec,"pixels":pixels,"triangles":len(faces),
                "repeats":repeats,"reference":baseline_hash,"effect":effect_hash,
                "wave_metrics":last_metrics,"modes":pairs,
                "ranking_with_wave":{mode:summarize([a/b for a,b in
                    zip(samples["tiles"]["on"],samples[mode]["on"])])
                    for mode in MODES},
                "ranking_without_wave":{mode:summarize([a/b for a,b in
                    zip(samples["tiles"]["off"],samples[mode]["off"])])
                    for mode in MODES}}
    finally:
        for fb,engine in engines.values():
            engine.executor.shutdown(wait=True)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",required=True)
    p.add_argument("--pixels",nargs="+",type=int,default=[32,64])
    p.add_argument("--repeats",type=int,default=15)
    p.add_argument("--max-seconds",type=float,default=600.)
    args=p.parse_args(argv)
    if not 15<=args.repeats<=30 or len(args.pixels)>2 or not args.pixels or any(x not in (32,64,128) for x in args.pixels) or not math.isfinite(args.max_seconds) or args.max_seconds<=0:
        p.error("Require 15..30 repeats, sizes 32, 64 or 128, positive deadline")
    start=time.monotonic()
    head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    sources={s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in SOURCES}
    output=Path(args.output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="are-wave-ranking-") as tmp:
        native,build=build_raster_kernel(Path(tmp)/"raster")
        kernel=NativeRasterKernel(native,build["binary_sha256"])
        wave_fn,wave_build=binary_bridge(tmp)
        rows=[]
        deadline=time.monotonic()+args.max_seconds
        for pixels in args.pixels:
            for name,spec in SCENES:
                row=measure_scene(name,spec,pixels,args.repeats,kernel,wave_fn,deadline)
                rows.append(row)
                print(json.dumps({"scene":name,"pixels":pixels,
                    "with_wave_x":{mode:row["ranking_with_wave"][mode]["median"] for mode in MODES},
                    "effect_cost_x":{mode:row["modes"][mode]["effect_cost_ratio_paired"]["median"] for mode in MODES}}),flush=True)
    if head!=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip() or sources!={s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in SOURCES}:
        raise RuntimeError("SPHEREPOP_BENCHMARK_SOURCE_CHANGED")
    report={"protocol":"are.spherepop-wave-ranked-benchmark.v1",
            "authority":"measured-single-host-CPU-only","head_sha":head,
            "environment":{"python":platform.python_version(),"numpy":np.__version__,
                           "platform":platform.platform(),"details":environment()},
            "source_sha256":sources,"bridge_build":wave_build,"raster_build":build,
            "timing_scope":"draw_mesh plus ownership-mask plus native-wave; excludes framebuffer clear, source build, image hash and receipt writing",
            "no_physical_gpu_comparison":True,
            "no_production_speedup_claim":True,
            "elapsed_wall_s":time.monotonic()-start,"rows":rows}
    report["sha256"]=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(",",":"),allow_nan=False,default=str).encode()).hexdigest()
    output.write_text(json.dumps(report,indent=2,default=str)+"\n",encoding="utf-8")

if __name__=="__main__":main()
