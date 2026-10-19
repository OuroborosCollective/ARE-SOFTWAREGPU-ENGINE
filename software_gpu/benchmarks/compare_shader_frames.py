"""Whole draw_mesh CPU comparison of pre-#113 and current VertexColor conversion.

Paired real framebuffer CPU measurements, exact RGBA8/float32-depth parity.
No GPU claim or assertion of a performance gain.
"""
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


def _spread(values):
    """Median, linearly interpolated IQR and unscaled median absolute deviation."""
    ordered = sorted(values)
    def q(fraction):
        index = (len(ordered) - 1) * fraction
        low = int(index)
        return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)]
                               - ordered[low]) * (index - low)
    median = statistics.median(ordered)
    return median, q(.75) - q(.25), statistics.median(abs(v - median) for v in ordered)


def validate(report):
    if not isinstance(report, dict) or report.get("sha256") != make_digest(report):
        raise ValueError("SHADER_FRAME_RECEIPT_DIGEST")
    if report.get("protocol") != "are.shader.full-frame-abba.v1" or report.get("repeats") != 15:
        raise ValueError("SHADER_FRAME_RECEIPT_PROTOCOL")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                   text=True).strip()
    if report.get("head_sha") != head:
        raise ValueError("SHADER_FRAME_RECEIPT_HEAD")
    sources = report.get("source_sha256")
    if not isinstance(sources, dict) or set(sources) != set(SOURCES):
        raise ValueError("SHADER_FRAME_RECEIPT_SOURCE")
    if any(sources[path] != hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
           for path in SOURCES):
        raise ValueError("SHADER_FRAME_RECEIPT_SOURCE")
    pixels, workers = report.get("pixels"), report.get("workers")
    if (type(pixels) is not int or not 32 <= pixels <= 256
            or type(workers) is not int or not 1 <= workers <= 8):
        raise ValueError("SHADER_FRAME_RECEIPT_CASES")
    expected = {(name, mode): count for name, count, _ in SCENES for mode in MODES}
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != len(expected):
        raise ValueError("SHADER_FRAME_RECEIPT_CASES")
    seen = set()
    scene_hashes = {}
    for c in cases:
        if not isinstance(c, dict):
            raise ValueError("SHADER_FRAME_RECEIPT_CASES")
        key = (c.get("scene"), c.get("mode"))
        if (key not in expected or key in seen
                or c.get("triangles") != expected[key]
                or c.get("pixels") != pixels or c.get("workers") != workers
                or type(c.get("covered_pixels")) is not int
                or not 10 < c["covered_pixels"] <= pixels * pixels
                or type(c.get("min_batch_fragment_samples")) is not int
                or (c["min_batch_fragment_samples"] <= 0 if key[1] == "plan-batch"
                    else c["min_batch_fragment_samples"] != 0)):
            raise ValueError("SHADER_FRAME_RECEIPT_CASES")
        seen.add(key)
        hashes = {name: c.get(name) for name in ("rgba_sha256", "depth_sha256")}
        if any(not isinstance(v, str) or len(v) != 64
               or any(ch not in "0123456789abcdef" for ch in v)
               for v in hashes.values()):
            raise ValueError("SHADER_FRAME_RECEIPT_HASHES")
        prev_hash = scene_hashes.setdefault(key[0], hashes)
        if hashes != prev_hash:
            raise ValueError("SHADER_FRAME_RECEIPT_HASHES")
        pairs = c.get("pairs")
        if not isinstance(pairs, list) or len(pairs) != 15:
            raise ValueError("SHADER_FRAME_RECEIPT_PAIRS")
        for i, pair in enumerate(pairs):
            order = ["previous", "current"] if i % 2 == 0 else ["current", "previous"]
            if (not isinstance(pair, dict) or pair.get("order") != order
                    or pair.get("hashes") != hashes
                    or any(type(pair.get(label + "_ms")) not in (int, float)
                           or not math.isfinite(pair[label + "_ms"])
                           or pair[label + "_ms"] <= 0 for label in ("previous", "current"))):
                raise ValueError("SHADER_FRAME_RECEIPT_PAIRS")
        previous = [p["previous_ms"] for p in pairs]
        current = [p["current_ms"] for p in pairs]
        ratios = [a / b for a, b in zip(previous, current)]
        if not all(math.isfinite(r) and r > 0 for r in ratios):
            raise ValueError("SHADER_FRAME_RECEIPT_TIMINGS")
        prev_med, prev_iqr, prev_mad = _spread(previous)
        curr_med, curr_iqr, curr_mad = _spread(current)
        metrics = {
            "median_previous_ms": prev_med, "median_current_ms": curr_med,
            "iqr_previous_ms": prev_iqr, "iqr_current_ms": curr_iqr,
            "mad_previous_ms": prev_mad, "mad_current_ms": curr_mad,
            "paired_median_speedup": statistics.median(ratios),
        }
        if any(type(c.get(field)) not in (float, int)
               or not math.isfinite(c[field])
               or not math.isclose(c[field], value, rel_tol=1e-12, abs_tol=1e-12)
               for field, value in metrics.items()):
            raise ValueError("SHADER_FRAME_RECEIPT_TIMINGS")
        faster = sum(b < a for a, b in zip(previous, current))
        if type(c.get("faster_pairs")) is not int or c["faster_pairs"] != faster:
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
        if mode=="plan-batch" and min(batch_samples,default=0)<=0:
            raise ValueError("SHADER_FRAME_BATCH_NOT_EXERCISED")
        return {"scene":name,"mode":mode,"triangles":count,"pixels":pixels,
                "workers":workers,"covered_pixels":covered_pixels,
                "rgba_sha256":reference["rgba_sha256"],
                "depth_sha256":reference["depth_sha256"],
                "min_batch_fragment_samples":min(batch_samples) if batch_samples else 0,
                "pairs":pairs,
                "median_previous_ms":statistics.median(x["previous_ms"] for x in pairs),
                "median_current_ms":statistics.median(x["current_ms"] for x in pairs),
                "iqr_previous_ms":_spread([x["previous_ms"] for x in pairs])[1],
                "iqr_current_ms":_spread([x["current_ms"] for x in pairs])[1],
                "mad_previous_ms":_spread([x["previous_ms"] for x in pairs])[2],
                "mad_current_ms":_spread([x["current_ms"] for x in pairs])[2],
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
