"""Source-bound 15-pair CPU comparison; no speedup assertion or GPU inference.

A/B and B/A variants are timed serially on identical CPU host conditions.
The reference and opt-in deferred backend must produce byte-identical RGBA8
and float32 depth at every trial. Receipts record both wins and regressions.
"""
from __future__ import annotations
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

from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex

ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    "software_gpu/graphics/deferred_visibility.py",
    "software_gpu/graphics/tile_backend.py",
    "software_gpu/graphics/rasterizer.py",
    "software_gpu/graphics/batch_shader.py",
    "software_gpu/graphics/geometry.py",
    "software_gpu/benchmarks/compare_deferred_visibility.py",
)
VARIANTS = ("tiles", "tiles-deferred")


def scene(layers: int):
    positions = ((-.9, -.9), (.9, -.9), (.9, .9), (-.9, .9))
    verts, faces = [], []
    for layer in range(layers):
        z = .75 - layer * .08
        offset = len(verts)
        for i, (x, y) in enumerate(positions):
            verts.append(Vertex(np.array((x, y, z, 1), dtype=np.float32),
                                color=np.array((.15 + .06*layer, .12 + .1*i, .65 - .04*layer))))
        faces += [(offset, offset+1, offset+2),
                  (offset, offset+2, offset+3)]
    return verts, faces


def render(vertices, faces, backend, pixels, workers):
    fb = Framebuffer(pixels, pixels)
    fb.clear(17, 31, 47, 239, depth=1.0)
    renderer = SoftwareRasterizer(fb, tile_size=16, num_threads=workers, backend=backend)
    try:
        start = time.perf_counter_ns()
        renderer.draw_mesh(vertices, faces, VertexColorShader())
        elapsed = (time.perf_counter_ns() - start) / 1e6
        receipt = renderer.last_deferred_receipt
        return elapsed, fb.color_buffer.tobytes(), fb.depth_buffer.tobytes(), receipt
    finally:
        renderer.executor.shutdown(wait=True)


def run(output, pixels=96, repeats=15, workers=2):
    if pixels not in (64, 96, 128) or repeats != 15 or workers not in (1, 2, 4):
        raise ValueError("DEFERRED_BENCH_BOUNDS")
    report = {
        "protocol": "are.deferred-visibility.abba.v1",
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES},
        "host": {"platform": platform.platform(), "logical_cpus": os.cpu_count(),
                 "affinity": sorted(os.sched_getaffinity(0))
                 if hasattr(os, "sched_getaffinity") else None,
                 "numpy": np.__version__},
        "pixels": pixels, "repeats": repeats, "workers": workers, "scenes": [],
        "limits": ["CPU-only", "serial AB/BA matched order",
                   "single draw per trial", "benchmark is not a general speedup proof"],
    }
    for layers in (1, 5):
        verts, faces = scene(layers)
        # The cold session warmups are real draws on both backends.
        baseline = None
        for variant in VARIANTS:
            for _ in range(2):
                _, rgba, z, _ = render(verts, faces, variant, pixels, workers)
                frame = hashlib.sha256(rgba + z).hexdigest()
                if baseline is None:
                    baseline = frame
                elif baseline != frame:
                    raise AssertionError("DEFERRED_FRAME_PARITY")
        pairs = []
        for i in range(repeats):
            order = VARIANTS if i % 2 == 0 else tuple(reversed(VARIANTS))
            times = {}
            counters = None
            for variant in order:
                elapsed, rgba, z, receipt = render(verts, faces, variant, pixels, workers)
                if hashlib.sha256(rgba + z).hexdigest() != baseline:
                    raise AssertionError("DEFERRED_FRAME_PARITY")
                times[variant] = elapsed
                if receipt is not None:
                    counters = receipt
            pairs.append({"index": i, "order": list(order),
                          "ms": times, "deferred_counters": counters})
        before = [p["ms"]["tiles"] for p in pairs]
        after = [p["ms"]["tiles-deferred"] for p in pairs]
        summary = {"layers": layers, "frame_sha256": baseline, "pairs": pairs,
                   "median_reference_ms": statistics.median(before),
                   "median_deferred_ms": statistics.median(after),
                   "median_paired_ratio": statistics.median(
                       b/a for a, b in zip(before, after)),
                   "deferred_faster_pairs": sum(b < a for a,b in zip(before,after))}
        report["scenes"].append(summary)
        print(json.dumps({k:v for k,v in summary.items() if k != "pairs"}),flush=True)
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    report["sha256"] = hashlib.sha256(encoded).hexdigest()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n",
                      encoding="utf-8")
    print("DEFERRED_BENCH_READBACK_OK", report["sha256"])
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--pixels", type=int, default=96)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--repeats", type=int, default=15)
    a=p.parse_args()
    run(a.output, a.pixels, a.repeats, a.workers)


if __name__ == "__main__":
    main()
