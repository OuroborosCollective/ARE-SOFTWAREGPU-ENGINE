"""Whole draw_mesh CPU comparison of pre-#113 and current VertexColor conversion.

Paired real framebuffer CPU measurements, exact RGBA8/float32-depth parity.
No GPU claim or assertion of a performance gain.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

import numpy as np

from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.surface_plan import SurfacePlanPolicy

ROOT=Path(__file__).resolve().parents[2]
SCENES=(("large-surfaces",8,.8),("small-triangles",160,.05))
MODES=("tiles-scalar","plan-batch")
SOURCES=("software_gpu/benchmarks/compare_shader_frames.py",
         "software_gpu/graphics/batch_shader.py",
         "software_gpu/graphics/rasterizer.py",
         "software_gpu/graphics/tile_backend.py",
         "software_gpu/graphics/geometry.py",
         "software_gpu/tests/test_shader_frames.py")
POLICY=SurfacePlanPolicy(scan_min_samples=sys.maxsize,
                          batch_min_samples=1,
                          draw_min_bbox_samples_per_triangle=0,
                          name="frame-batch-noscan-ablation")


class PreviousVertexColor(VertexColorShader):
    def fragment_shader(self, varyings):
        rgb=np.clip(np.asarray(varyings["color"])*255,0,255).astype(np.uint8)
        return int(rgb[0]),int(rgb[1]),int(rgb[2]),255

    batch_fragment_equivalent_to=fragment_shader

    def fragment_shader_batch(self, varyings):
        color=np.asarray(varyings["color"])
        if color.ndim!=2 or color.shape[1]!=3 or not np.isfinite(color).all():
            raise ValueError("BATCH_COLOR_INPUT_INVALID")
        rgb=np.clip(color*255,0,255).astype(np.uint8)
        rgba=np.empty((len(rgb),4),dtype=np.uint8)
        rgba[:,:3]=rgb
        rgba[:,3]=255
        return rgba


def make_digest(report):
    payload={k:v for k,v in report.items() if k!="sha256"}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),
                                      allow_nan=False).encode()).hexdigest()


def validate(report):
    if report.get("sha256")!=make_digest(report):
        raise ValueError("SHADER_FRAME_RECEIPT_DIGEST")
    if report.get("protocol")!="are.shader.full-frame-abba.v1" or report.get("repeats")!=15:
        raise ValueError("SHADER_FRAME_RECEIPT_PROTOCOL")
    if len(report.get("cases",[]))!=4:
        raise ValueError("SHADER_FRAME_RECEIPT_CASES")
    seen=set()
    for c in report["cases"]:
        k=(c.get("scene"),c.get("mode"))
        if k not in {(s,m) for s,_,_ in SCENES for m in MODES} or k in seen:
            raise ValueError("SHADER_FRAME_RECEIPT_CASES")
        seen.add(k)
        pairs=c.get("pairs",[])
        if len(pairs)!=15:
            raise ValueError("SHADER_FRAME_RECEIPT_PAIRS")
        h={"rgba_sha256":c.get("rgba_sha256"),"depth_sha256":c.get("depth_sha256")}
        if any(not isinstance(x,str) or len(x)!=64 for x in h.values()):
            raise ValueError("SHADER_FRAME_RECEIPT_HASHES")
        for i,p in enumerate(pairs):
            order=["previous","current"] if i%2==0 else ["current","previous"]
            if (p.get("order")!=order or p.get("hashes")!=h or
                any(type(p.get(x+"_ms")) not in (int,float) or p[x+"_ms"]<=0
                    for x in ("previous","current"))):
                raise ValueError("SHADER_FRAME_RECEIPT_PAIRS")
        speed=statistics.median(p["previous_ms"]/p["current_ms"] for p in pairs)
        faster=sum(p["current_ms"]<p["previous_ms"] for p in pairs)
        if (abs(speed-c["paired_median_speedup"])>1e-12
                or faster!=c["faster_pairs"]):
            raise ValueError("SHADER_FRAME_RECEIPT_TIMINGS")
    return True


def measure_case(name,count,radius,mode,pixels=96,workers=2,repeats=15):
    if mode not in MODES or repeats<1:
        raise ValueError("SHADER_FRAME_MODE")
    verts,faces=make_fixture(count,radius)
    backend="tiles" if mode=="tiles-scalar" else "tiles-plan"
    engines={}
    try:
        for label,shader in (("previous",PreviousVertexColor()),
                             ("current",VertexColorShader())):
            fb=Framebuffer(pixels,pixels)
            engines[label]=(fb,SoftwareRasterizer(
                fb,backend=backend,tile_size=16,num_threads=workers,
                plan_policy=POLICY if backend=="tiles-plan" else None),shader)
        pairs=[]
        reference=None
        batch_samples=[]
        covered_pixels=0
        for iteration in range(repeats+1):
            order=("previous","current") if iteration%2 else ("current","previous")
            if iteration==0:
                order=("previous","current")
            timings,hashes={},{}
            for label in order:
                fb,engine,shader=engines[label]
                fb.clear(13,23,47,255,depth=1.)
                t=time.perf_counter_ns()
                engine.draw_mesh(verts,faces,shader)
                timings[label]=(time.perf_counter_ns()-t)/1e6
                hashes[label]={
                    "rgba_sha256":hashlib.sha256(fb.color_buffer.tobytes()).hexdigest(),
                    "depth_sha256":hashlib.sha256(fb.depth_buffer.tobytes()).hexdigest()}
                if mode=="plan-batch":
                    receipt=engine.last_plan_receipt
                    if receipt is None or receipt["decision"]!="planned":
                        raise ValueError("SHADER_FRAME_BATCH_POLICY_UNEXPECTED")
                    batch_samples.append(receipt["counts"]["batch_fragment_samples"])
                covered_pixels=max(covered_pixels,int(np.count_nonzero(fb.depth_buffer<1.)))
            if hashes["previous"]!=hashes["current"]:
                raise ValueError("SHADER_FRAME_RGBA_OR_DEPTH_CHANGED")
            if reference is None:
                reference=hashes["previous"]
            elif reference!=hashes["previous"]:
                raise ValueError("SHADER_FRAME_NONDETERMINISTIC_BUFFER")
            if iteration:
                pairs.append({"order":list(order),
                              "previous_ms":timings["previous"],
                              "current_ms":timings["current"],
                              "hashes":hashes["current"]})
        if mode=="plan-batch" and max(batch_samples,default=0)==0:
            raise ValueError("SHADER_FRAME_BATCH_NOT_EXERCISED")
        return {"scene":name,"mode":mode,"triangles":count,"pixels":pixels,
                "workers":workers,"covered_pixels":covered_pixels,
                "rgba_sha256":reference["rgba_sha256"],
                "depth_sha256":reference["depth_sha256"],
                "min_batch_fragment_samples":min(batch_samples) if batch_samples else 0,
                "pairs":pairs,
                "median_previous_ms":statistics.median(x["previous_ms"] for x in pairs),
                "median_current_ms":statistics.median(x["current_ms"] for x in pairs),
                "paired_median_speedup":statistics.median(
                    x["previous_ms"]/x["current_ms"] for x in pairs),
                "faster_pairs":sum(x["current_ms"]<x["previous_ms"] for x in pairs)}
    finally:
        for _,engine,_ in engines.values():
            engine.executor.shutdown(wait=True)


def run(output,pixels=96,workers=2):
    if pixels<32 or pixels>256 or workers<1 or workers>8:
        raise ValueError("SHADER_FRAME_BENCHMARK_BOUNDS")
    report={"protocol":"are.shader.full-frame-abba.v1","repeats":15,
            "head_sha":subprocess.check_output(
                ["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
            "pixels":pixels,"workers":workers,
            "host":{"platform":platform.platform(),"python":sys.version.split()[0],
                    "numpy":np.__version__,"logical_cpus":os.cpu_count()},
            "source_sha256":{s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest()
                             for s in SOURCES},
            "scope":"full draw_mesh CPU; RGBA8 and float32 depth parity",
            "cases":[measure_case(name,n,r,mode,pixels,workers,15)
                     for name,n,r in SCENES for mode in MODES]}
    report["sha256"]=make_digest(report)
    target=Path(output)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("x",encoding="utf-8") as f:
        json.dump(report,f,sort_keys=True,indent=2,allow_nan=False)
        f.write("\n")
    saved=json.loads(target.read_text(encoding="utf-8"))
    validate(saved)
    if saved!=report:
        raise ValueError("SHADER_FRAME_RECEIPT_READBACK")
    for case in saved["cases"]:
        print("SHADER_FRAME_ABBA",case["scene"],case["mode"],
              round(case["paired_median_speedup"],4),
              case["faster_pairs"],"/15",flush=True)
    print("SHADER_FRAME_RECEIPT_OK",saved["sha256"],flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--output",required=True)
    p.add_argument("--pixels",type=int,default=96)
    p.add_argument("--workers",type=int,default=2)
    a=p.parse_args()
    run(a.output,a.pixels,a.workers)
