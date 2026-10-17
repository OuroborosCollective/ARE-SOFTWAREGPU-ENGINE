"""15-pair real CPU microbenchmarks for three shader hotpath changes.

This is per-function work with exact outputs, NOT whole-frame CPU/GPU FPS.
It never claims a speedup until source-bound raw timings have been collected.
"""
from __future__ import annotations

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

from software_gpu.graphics.batch_shader import VertexColorShader

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = (
    "software_gpu/graphics/shader.py",
    "software_gpu/graphics/batch_shader.py",
    "software_gpu/benchmarks/compare_shader_hotpaths.py",
    "software_gpu/tests/test_shader_clamp_optimizations.py",
)


def blinn_baseline(r, g, b):
    if math.isnan(r) or math.isnan(g) or math.isnan(b):
        raise ValueError("cannot convert float NaN to integer")
    return (
        int(min(1.0, max(0.0, r)) * 255.0),
        int(min(1.0, max(0.0, g)) * 255.0),
        int(min(1.0, max(0.0, b)) * 255.0), 255
    )


def blinn_inline(r, g, b):
    if r != r or g != g or b != b:
        raise ValueError("cannot convert float NaN to integer")
    return (
        int((r if r < 1.0 else 1.0) * 255.0) if r > 0.0 else 0,
        int((g if g < 1.0 else 1.0) * 255.0) if g > 0.0 else 0,
        int((b if b < 1.0 else 1.0) * 255.0) if b > 0.0 else 0,
        255
    )


def vertex_baseline(color):
    rgb = np.clip(np.asarray(color) * 255, 0, 255).astype(np.uint8)
    return int(rgb[0]), int(rgb[1]), int(rgb[2]), 255


def batch_baseline(color):
    color = np.asarray(color)
    if color.ndim != 2 or color.shape[1] != 3 or not np.isfinite(color).all():
        raise ValueError("BATCH_COLOR_INPUT_INVALID")
    rgb = np.clip(color * 255, 0, 255).astype(np.uint8)
    rgba = np.empty((len(rgb), 4), dtype=np.uint8)
    rgba[:, :3] = rgb
    rgba[:, 3] = 255
    return rgba


def parity_inputs():
    rng = np.random.default_rng(20261017)
    scalar = [rng.uniform(-0.1, 1.1, size=3).astype(np.float32)
              for _ in range(1200)]
    scalar += [
        np.array([x, -x, 1.0], dtype=np.float32)
        for x in (-3.0, -0.0, 0.0, 0.5, 0.99999994, 1.0, 2.0)
    ]
    batch = [rng.uniform(-0.1, 1.1, size=(1024, 3)).astype(np.float32)
             for _ in range(16)]
    return scalar, batch


def verify_inputs(scalar, batches):
    shader = VertexColorShader()
    for sample in scalar:
        if vertex_baseline(sample) != shader.fragment_shader({"color": sample}):
            raise ValueError("SHADER_HOTPATH_SCALAR_PARITY")
    for sample in batches:
        color_before = sample.copy()
        if not np.array_equal(batch_baseline(sample),
                              shader.fragment_shader_batch({"color": sample})):
            raise ValueError("SHADER_HOTPATH_BATCH_PARITY")
        if not np.array_equal(sample, color_before):
            raise ValueError("SHADER_HOTPATH_INPUT_MUTATED")
    for r, g, b in ((0.0, 0.5, 1.0), (-3.0, 2.0, 0.8),
                    (float("-inf"), float("inf"), 0.0)):
        if blinn_baseline(r, g, b) != blinn_inline(r, g, b):
            raise ValueError("SHADER_HOTPATH_BLINN_PARITY")
    for which in (blinn_baseline, blinn_inline):
        try:
            which(float("nan"), 0.5, 0.5)
        except ValueError:
            pass
        else:
            raise ValueError("SHADER_HOTPATH_BLINN_NAN_NOT_REJECTED")


def measurements(reference, optimized, repeats):
    for _ in range(3):
        if reference() != optimized():
            raise ValueError("SHADER_HOTPATH_WARMUP_PARITY")
    samples = []
    for i in range(repeats):
        order = ("reference", "optimized") if i % 2 == 0 else ("optimized", "reference")
        observations = {}
        for variant in order:
            func = reference if variant == "reference" else optimized
            start = time.perf_counter_ns()
            value = func()
            elapsed = (time.perf_counter_ns() - start) / 1e6
            observations[variant] = {"ms": elapsed, "output": value}
        if observations["reference"]["output"] != observations["optimized"]["output"]:
            raise ValueError("SHADER_HOTPATH_PAIRED_OUTPUT_MISMATCH")
        samples.append({
            "order": list(order),
            "baseline_ms": float(observations["reference"]["ms"]),
            "candidate_ms": float(observations["optimized"]["ms"]),
        })
    left = [x["baseline_ms"] for x in samples]
    right = [x["candidate_ms"] for x in samples]
    ratios = [b / a for b, a in zip(left, right)]
    quartiles = np.percentile(right, [25, 75])
    return {
        "pairs": samples,
        "median_baseline_ms": statistics.median(left),
        "median_candidate_ms": statistics.median(right),
        "median_paired_ratio": statistics.median(ratios),
        "candidate_iqr_ms": float(quartiles[1] - quartiles[0]),
        "candidate_mad_ms": statistics.median(
            abs(v - statistics.median(right)) for v in right
        ),
        "candidate_faster_pairs": sum(x["candidate_ms"] < x["baseline_ms"]
                                      for x in samples),
    }


def sha_payload(report):
    body = {k: v for k, v in report.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def run(output, repeats=15):
    if repeats != 15:
        raise ValueError("SHADER_HOTPATH_REPEATS_15_REQUIRED")
    scalar, batches = parity_inputs()
    verify_inputs(scalar, batches)
    shader = VertexColorShader()
    triples = [tuple(float(x) for x in arr) for arr in scalar]
    def ref_blinn():
        return sum(sum(blinn_baseline(*triple)[:3]) for triple in triples)
    def new_blinn():
        return sum(sum(blinn_inline(*triple)[:3]) for triple in triples)
    def ref_scalar():
        return sum(sum(vertex_baseline(row)[:3]) for row in scalar)
    def new_scalar():
        return sum(sum(shader.fragment_shader({"color": row})[:3]) for row in scalar)
    def ref_batch():
        return sum(int(batch_baseline(row)[:, 0].sum()) for row in batches)
    def new_batch():
        return sum(int(shader.fragment_shader_batch({"color": row})[:, 0].sum())
                   for row in batches)
    report = {
        "protocol": "are.shader.hotpath.microbench.v1",
        "scope": "CPU function-only, same real inputs; NOT frame FPS or GPU parity",
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
                          for p in SOURCE_PATHS},
        "host": {
            "platform": platform.platform(), "python": sys.version.split()[0],
            "numpy": np.__version__, "logical_cpus": os.cpu_count(),
            "affinity": (sorted(os.sched_getaffinity(0))
                         if hasattr(os, "sched_getaffinity") else None),
        },
        "repeats": repeats,
        "cases": {
            "blinn_channel_clamp_only": measurements(ref_blinn, new_blinn, repeats),
            "vertex_color_full_scalar_function": measurements(ref_scalar, new_scalar, repeats),
            "vertex_color_full_batch_function": measurements(ref_batch, new_batch, repeats),
        },
        "frame_parity": "separate actual framebuffer tests; not proven by microbenchmark",
        "status": "PASS",
    }
    report["sha256"] = sha_payload(report)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, sort_keys=True,
                  allow_nan=False)
        f.write("\n")
    saved = json.loads(target.read_text(encoding="utf-8"))
    if saved != report or saved["sha256"] != sha_payload(saved):
        raise ValueError("SHADER_HOTPATH_RECEIPT_READBACK_FAILED")
    print(json.dumps({
        "status": saved["status"], "sha256": saved["sha256"],
        "source_head": saved["source_head"],
        "cases": {name: {"median_paired_ratio": m["median_paired_ratio"],
                          "faster_pairs": m["candidate_faster_pairs"]}
                  for name, m in saved["cases"].items()}
    }, sort_keys=True), flush=True)
    return saved


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--repeats", type=int, default=15)
    options = p.parse_args()
    run(options.output, options.repeats)


if __name__ == "__main__":
    main()
