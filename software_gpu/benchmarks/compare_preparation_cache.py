"""Real cold/warm/full-draw-invalidation CPU cache experiment, opt-in only.

Every mode re-rasterizes and shades every draw against the same current inputs.
Times include keying, cache copies/accounting, lookup, setup, binning and shading.
Scenarios mutate outside timed draws; framebuffer clears are also outside.
"""
import argparse
import hashlib
import html
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

from .compare_surface_plans import SCENES, build_scene, environment, summarize
from ..graphics.batch_shader import VertexColorShader
from ..graphics.framebuffer import Framebuffer
from ..graphics.rasterizer import SoftwareRasterizer
from ..graphics.surface_plan import BATCH_FIRST_POLICY


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = (
    "software_gpu/benchmarks/compare_preparation_cache.py",
    "software_gpu/benchmarks/compare_surface_plans.py",
    "software_gpu/benchmarks/compare_tile_backends.py",
    "software_gpu/integrations/aurion/offline_render_worker.py",
    *("software_gpu/graphics/" + name for name in (
        "preparation_cache.py", "rasterizer.py", "geometry.py", "tile_backend.py",
        "surface_plan.py", "framebuffer.py", "batch_shader.py", "shader.py")))
SCENARIOS = ("static", "one-vertex", "all-vertices")
MODES = ("uncached", "cache-warm", "cache-cold")


def sources():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_PATHS}


def measure_case(name, spec, pixels, repeats, workers, scenario, cache_bytes, deadline=None):
    mesh, faces = build_scene(spec)
    initial = [vertex.position.copy() for vertex in mesh]
    engines = {}
    samples = {mode: [] for mode in MODES}
    cache_receipts = {mode: [] for mode in MODES if mode != "uncached"}
    frames = []
    try:
        for mode in MODES:
            fb = Framebuffer(pixels, pixels)
            engines[mode] = SoftwareRasterizer(
                fb, num_threads=workers, backend="tiles-plan", plan_policy=BATCH_FIRST_POLICY,
                preparation_cache_bytes=0 if mode == "uncached" else cache_bytes)
        for run in range(repeats + 1):
            if scenario != "static":
                selected = range(len(mesh)) if scenario == "all-vertices" else (0,)
                for i in selected:
                    mesh[i].position[0] = initial[i][0] + np.float32(run * .0005)
            offset = run % len(MODES)
            order = MODES[offset:] + MODES[:offset]
            reference = None
            reference_plan = None
            for mode in order:
                if deadline is not None and time.monotonic() >= deadline:
                    raise RuntimeError("PREPARATION_CACHE_BENCHMARK_BUDGET_EXCEEDED")
                engine = engines[mode]
                engine.fb.clear(16, 25, 38, 255, depth=1.0)
                start = time.perf_counter_ns()
                if mode == "cache-cold":
                    engine.preparation_cache.clear()
                engine.draw_mesh(mesh, faces, VertexColorShader())
                elapsed = (time.perf_counter_ns() - start) / 1e6
                image = engine.fb.color_buffer.tobytes() + engine.fb.depth_buffer.tobytes()
                if reference is None:
                    reference, reference_plan = image, engine.last_plan_receipt
                elif image != reference or engine.last_plan_receipt != reference_plan:
                    raise AssertionError("PREPARATION_CACHE_COLOR_DEPTH_OR_PLAN_MISMATCH")
                receipt = engine.last_preparation_receipt
                if mode != "uncached":
                    expected = "hit" if mode == "cache-warm" and scenario == "static" and run else "miss"
                    if receipt["status"] != expected:
                        raise AssertionError("PREPARATION_CACHE_EXPECTED_" + expected + ":" + str(receipt))
                    if run:
                        cache_receipts[mode].append(receipt)
                if run:
                    samples[mode].append(elapsed)
            if run:
                frames.append({"color_sha256": hashlib.sha256(engine.fb.color_buffer.tobytes()).hexdigest(),
                               "depth_sha256": hashlib.sha256(engine.fb.depth_buffer.tobytes()).hexdigest(),
                               "color_depth_sha256": hashlib.sha256(reference).hexdigest()})
        return {"scene": name, "scene_spec": spec, "scenario": scenario, "pixels": pixels,
                "workers": workers, "repeats": repeats, "warmups": 1, "byte_identical": True,
                "samples_ms": samples, "stats_ms": {mode: summarize(values) for mode, values in samples.items()},
                "speedup_paired": {mode: statistics.median(a / b for a, b in zip(samples["uncached"], values))
                                   for mode, values in samples.items()},
                "cache_receipts": cache_receipts, "frames": frames}
    finally:
        for engine in engines.values():
            engine.executor.shutdown(wait=True)


def write_report(destination, receipt):
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "preparation-cache-benchmark.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    rows = []
    for case in receipt["results"]:
        for mode in MODES:
            stats = case["stats_ms"][mode]
            rows.append("<tr>" + "".join("<td>" + html.escape(str(value)) + "</td>" for value in (
                case["scene"], case["scenario"], mode, round(stats["median"], 3), round(stats["iqr"], 3),
                round(stats["mad"], 3), stats["n"], round(case["speedup_paired"][mode], 3))) + "</tr>")
    (destination / "preparation-cache-report.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Preparation cache experiment</title>'
        '<style>body{font:16px system-ui;margin:2rem}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.5rem}</style>'
        '<h1>Preparation cache: real CPU draws</h1><p>All color/depth bytes and plan receipts matched per frame. '
        'Draw-level invalidation; opt-in only; no GPU-parity claim. Cold time includes clear/copies/accounting. '
        'Warm time includes full input hashing. Higher than 1 means faster.</p>'
        '<table><tr><th>Scene</th><th>Scenario</th><th>Mode</th><th>Median ms</th><th>IQR</th><th>MAD</th>'
        '<th>n</th><th>Paired ratio</th></tr>' + "".join(rows) + "</table></html>\n", encoding="utf-8")


def audit(receipt, root=None):
    """Consistency/source check only; this does not independently rerender."""
    if (receipt.get("protocol") != "are.preparation-cache-benchmark.v1"
            or set(receipt.get("source_paths_sha256", {})) != set(SOURCE_PATHS)):
        raise ValueError("PREPARATION_CACHE_ARTIFACT_SOURCE_BINDING_INVALID")
    if root is not None:
        for name, digest in receipt["source_paths_sha256"].items():
            if hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() != digest:
                raise ValueError("PREPARATION_CACHE_ARTIFACT_SOURCE_MISMATCH")
    draws = 0
    for case in receipt["results"]:
        n = case["repeats"]
        if case["byte_identical"] is not True or len(case["frames"]) != n or set(case["samples_ms"]) != set(MODES):
            raise ValueError("PREPARATION_CACHE_ARTIFACT_PARITY_INVALID")
        for mode in MODES:
            values = case["samples_ms"][mode]
            if len(values) != n or any(not math.isfinite(v) or v <= 0 for v in values):
                raise ValueError("PREPARATION_CACHE_ARTIFACT_TIMINGS_INVALID")
            stats = summarize(values)
            paired = statistics.median(a / b for a, b in zip(case["samples_ms"]["uncached"], values))
            if stats != case["stats_ms"][mode] or paired != case["speedup_paired"][mode]:
                raise ValueError("PREPARATION_CACHE_ARTIFACT_STATISTICS_INVALID")
            if mode != "uncached":
                entries = case["cache_receipts"][mode]
                expected = "hit" if mode == "cache-warm" and case["scenario"] == "static" else "miss"
                if len(entries) != n or any(
                        row["status"] != expected or not 0 <= row["retained_bytes"] <= row["max_bytes"]
                        or not 0 <= row["entries"] <= row["max_entries"] for row in entries):
                    raise ValueError("PREPARATION_CACHE_ARTIFACT_CACHE_STATE_INVALID")
            draws += n + 1
    return {"status": "PREPARATION_CACHE_ARTIFACT_OK", "cases": len(receipt["results"]),
            "draws_including_warmups": draws,
            "source_verification": "checkout-match" if root is not None else "artifact-only"}


def _run_budgeted(args):
    destination = args.output_dir.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".preparation-cache-", dir=destination.parent) as temporary:
        command = [sys.executable, "-m", "software_gpu.benchmarks.compare_preparation_cache",
                   "--output-dir", temporary, "--pixels", str(args.pixels), "--workers", str(args.workers),
                   "--repeats", str(args.repeats), "--cache-mib", str(args.cache_mib),
                   "--max-seconds", str(args.max_seconds), "--budget-child",
                   "--scenes", *args.scenes, "--scenarios", *args.scenarios]
        try:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=args.max_seconds)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("PREPARATION_CACHE_BENCHMARK_BUDGET_EXCEEDED") from error
        sys.stderr.write(result.stderr)
        if result.returncode:
            raise RuntimeError("PREPARATION_CACHE_BENCHMARK_CHILD_FAILED")
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("preparation-cache-benchmark.json", "preparation-cache-report.html"):
            os.replace(Path(temporary) / name, destination / name)
        sys.stdout.write(result.stdout)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--pixels", type=int, default=128)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--cache-mib", type=int, default=32)
    parser.add_argument("--scenes", nargs="+", choices=[name for name, _ in SCENES],
                        default=[name for name, _ in SCENES])
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=list(SCENARIOS))
    parser.add_argument("--max-seconds", type=float, default=900.)
    parser.add_argument("--budget-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (not 32 <= args.pixels <= 1024 or not 1 <= args.workers <= 16 or not 1 <= args.repeats <= 30
            or not 1 <= args.cache_mib <= 256 or not math.isfinite(args.max_seconds) or args.max_seconds < 0):
        parser.error("pixels 32-1024, workers 1-16, repeats 1-30, cache-mib 1-256, finite budget >=0 required")
    if args.max_seconds and not args.budget_child:
        _run_budgeted(args)
        return
    if args.repeats < 15:
        print("warning: fewer than 15 repeats", file=sys.stderr)
    before = sources()
    deadline = time.monotonic() + args.max_seconds if args.max_seconds else None
    results = []
    for name, spec in SCENES:
        if name not in args.scenes:
            continue
        for scenario in args.scenarios:
            results.append(measure_case(name, spec, args.pixels, args.repeats, args.workers,
                                        scenario, args.cache_mib << 20, deadline))
            print("PREPARATION_CACHE_CASE_OK:" + name + ":" + scenario, file=sys.stderr, flush=True)
    if before != sources():
        raise RuntimeError("PREPARATION_CACHE_SOURCE_CHANGED_DURING_RUN")
    receipt = {"protocol": "are.preparation-cache-benchmark.v1", "activation": "EXPLICIT_OPT_IN_ONLY",
               "python": platform.python_version(), "os": platform.platform(), "numpy": np.__version__,
               "environment": environment(), "source_paths_sha256": before,
               "budget_seconds": args.max_seconds, "cache_bytes": args.cache_mib << 20,
               "results": results}
    audit(receipt, root=ROOT)
    write_report(args.output_dir, receipt)
    print(json.dumps({"status": "PREPARATION_CACHE_BENCHMARK_OK", "cases": len(results),
                      "byte_identical": all(case["byte_identical"] for case in results)}))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
