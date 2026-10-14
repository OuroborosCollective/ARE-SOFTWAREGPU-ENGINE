"""Fair, source-bound 3-way CPU research: scalar vs batch-first vs deferred.

All variants render the same submitted geometry, color and float32 depth.
15 serial balanced 3-position rotations, and no automatic production tuning.
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
from software_gpu.graphics.surface_plan import BATCH_FIRST_POLICY
from software_gpu.benchmarks.compare_deferred_visibility import scene

PROTOCOL = "are.deferred.threeway.v1"
VARIANTS = ("tiles", "batch-first", "tiles-deferred")
SCENES = ((1, "far-first"), (5, "far-first"), (5, "near-first"))
ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    "software_gpu/benchmarks/compare_deferred_threeway.py",
    "software_gpu/benchmarks/compare_deferred_visibility.py",
    "software_gpu/graphics/deferred_visibility.py",
    "software_gpu/graphics/rasterizer.py",
    "software_gpu/graphics/tile_backend.py",
    "software_gpu/graphics/surface_plan.py",
    "software_gpu/graphics/batch_shader.py",
    "software_gpu/graphics/geometry.py",
    "software_gpu/tests/test_deferred_threeway.py",
)


def order_for_pair(i):
    if type(i) is not int or i < 0:
        raise ValueError("THREEWAY_PAIR_INDEX")
    return tuple(VARIANTS[(i + j) % len(VARIANTS)] for j in range(len(VARIANTS)))


def make_scene(layers, ordering):
    if layers not in (1, 5) or ordering not in ("near-first", "far-first"):
        raise ValueError("THREEWAY_SCENE_UNSUPPORTED")
    vertices, faces = scene(layers)
    if ordering == "near-first":
        faces = [face for n in reversed(range(layers)) for face in faces[n*2:n*2+2]]
    return vertices, faces


def measure_one(mesh, faces, variant, pixels, workers):
    if variant not in VARIANTS:
        raise ValueError("THREEWAY_VARIANT_UNSUPPORTED")
    fb = Framebuffer(pixels, pixels)
    fb.clear(17, 31, 47, 239, depth=1.)
    backend = "tiles-plan" if variant == "batch-first" else variant
    raster = SoftwareRasterizer(
        fb, tile_size=16, num_threads=workers, backend=backend,
        plan_policy=BATCH_FIRST_POLICY if variant == "batch-first" else None
    )
    try:
        start = time.perf_counter_ns()
        raster.draw_mesh(mesh, faces, VertexColorShader())
        ms = (time.perf_counter_ns() - start) / 1e6
        hashes = {
            "rgba_sha256": hashlib.sha256(fb.color_buffer.tobytes()).hexdigest(),
            "depth_sha256": hashlib.sha256(fb.depth_buffer.tobytes()).hexdigest()
        }
        if variant == "batch-first":
            plan = raster.last_plan_receipt
            if plan is None or plan["decision"] != "planned":
                raise AssertionError("THREEWAY_BATCH_NOT_ACTIVE")
            counts = plan["counts"]
            if counts["shaded_samples"] != counts["batch_fragment_samples"]:
                raise AssertionError("THREEWAY_BATCH_NOT_ACTIVE")
            detail = {"decision": plan["decision"], "policy": plan["policy"],
                      "batch_fragment_samples": counts["batch_fragment_samples"]}
        elif variant == "tiles-deferred":
            detail = raster.last_deferred_receipt
        else:
            detail = {"backend": "tiles"}
        return ms, hashes, detail
    finally:
        raster.executor.shutdown(wait=True)


def summarize(pairs):
    keys = {
        "deferred_vs_scalar": ("tiles", "tiles-deferred"),
        "deferred_vs_batch": ("batch-first", "tiles-deferred"),
        "batch_vs_scalar": ("tiles", "batch-first")
    }
    return {
        "medians_ms": {name: statistics.median(p["ms"][name] for p in pairs)
                       for name in VARIANTS},
        "speedup_paired": {key: statistics.median(
            p["ms"][baseline] / p["ms"][candidate] for p in pairs)
            for key, (baseline, candidate) in keys.items()},
        "faster_pairs": {key: sum(
            p["ms"][candidate] < p["ms"][baseline] for p in pairs)
            for key, (baseline, candidate) in keys.items()},
    }


def digest(report):
    payload = {k: v for k, v in report.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


def validate_report(report):
    if report.get("sha256") != digest(report):
        raise ValueError("THREEWAY_RECEIPT_HASH")
    if report.get("protocol") != PROTOCOL or report.get("repeats") != 15:
        raise ValueError("THREEWAY_PROTOCOL")
    if report.get("variants") != list(VARIANTS):
        raise ValueError("THREEWAY_VARIANTS")
    if len(report.get("scenes", [])) != len(SCENES):
        raise ValueError("THREEWAY_SCENES")
    for case, expected in zip(report["scenes"], SCENES):
        if (case.get("layers"), case.get("ordering")) != expected:
            raise ValueError("THREEWAY_SCENE_METADATA")
        pairs = case.get("pairs", [])
        if len(pairs) != 15:
            raise ValueError("THREEWAY_PAIRS")
        for i, p in enumerate(pairs):
            if p.get("order") != list(order_for_pair(i)):
                raise ValueError("THREEWAY_ORDER")
            if set(p["ms"]) != set(VARIANTS) or not all(
                    type(v) is float and 0 < v < float("inf")
                    for v in p["ms"].values()):
                raise ValueError("THREEWAY_TIMINGS")
        expected_stats = summarize(pairs)
        if case.get("summary") != expected_stats:
            raise ValueError("THREEWAY_SUMMARY")
        if len(case.get("frame_hashes", {})) != 2 or not all(
                len(h) == 64 and all(c in "0123456789abcdef" for c in h)
                for h in case["frame_hashes"].values()):
            raise ValueError("THREEWAY_FRAME_HASH")
    return True


def run(output, pixels=96, workers=2, repeats=15):
    if pixels not in (64, 96, 128) or workers not in (1, 2, 4) or repeats != 15:
        raise ValueError("THREEWAY_BOUNDS")
    source_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    report = {
        "protocol": PROTOCOL, "status": "PASS", "source_head": source_head,
        "source_sha256": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
                          for p in SOURCES},
        "host": {"platform": platform.platform(), "logical_cpus": os.cpu_count(),
                 "numpy": np.__version__,
                 "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None},
        "pixels": pixels, "workers": workers, "repeats": repeats,
        "variants": list(VARIANTS), "scenes": [],
        "limits": ["CPU-only", "same-host", "batch-first-control",
                   "no general GPU or game FPS claim"],
    }
    for layers, ordering in SCENES:
        mesh, faces = make_scene(layers, ordering)
        frame_hashes = None
        for variant in VARIANTS:
            for _ in range(2):
                _, hashes, _ = measure_one(mesh, faces, variant, pixels, workers)
                if frame_hashes is None:
                    frame_hashes = hashes
                elif hashes != frame_hashes:
                    raise AssertionError("THREEWAY_FRAME_PARITY")
        pairs = []
        for i in range(repeats):
            timings, observations = {}, {}
            order = order_for_pair(i)
            for variant in order:
                ms, hashes, details = measure_one(mesh, faces, variant, pixels, workers)
                if hashes != frame_hashes:
                    raise AssertionError("THREEWAY_FRAME_PARITY")
                timings[variant] = float(ms)
                observations[variant] = details
            pairs.append({"pair": i, "order": list(order),
                          "ms": timings, "details": observations})
        case = {
            "layers": layers, "ordering": ordering, "pairs": pairs,
            "frame_hashes": frame_hashes, "summary": summarize(pairs)
        }
        report["scenes"].append(case)
        print(json.dumps({"scene": [layers, ordering], **case["summary"]},
                         sort_keys=True), flush=True)
    report["sha256"] = digest(report)
    if not validate_report(report):
        raise AssertionError("THREEWAY_RECEIPT_INVALID")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n")
    saved = json.loads(output.read_text())
    validate_report(saved)
    if saved != report:
        raise AssertionError("THREEWAY_READBACK")
    print("THREEWAY_RECEIPT_READBACK_OK", saved["sha256"])
    return saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--pixels", type=int, default=96)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=15)
    a = parser.parse_args()
    run(a.output, a.pixels, a.workers, a.repeats)


if __name__ == "__main__":
    main()
