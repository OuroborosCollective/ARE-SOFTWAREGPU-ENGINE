"""Real CPU A/B: tiles, planned scalar, planned vertex-color batch.

Timings include mesh preparation, classification, shading and graph receipts.
This is a same-host observation, not a GPU comparison or automatic activation.

``--ablation`` adds a 2x2 factorial of the planned path with the draw-level
fallback forced off: corner scan on/off x batch shading on/off. All four share
the receipt and instrumentation base, so scan benefit, batch benefit and the
plan's own overhead can be separated. Each run reports median, IQR (linear
percentiles), unscaled MAD, min/max and raw samples; ``speedup_paired`` uses the
per-repeat ratio, which suits the rotated, interleaved run order.
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

from software_gpu.benchmarks.compare_tile_backends import FlatShader, make_fixture
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex
from software_gpu.graphics.surface_plan import SurfacePlanPolicy, BATCH_FIRST_POLICY, ADAPTIVE_PLAN_POLICY
from software_gpu.integrations.aurion.offline_render_worker import (
    _camera_transform, _orient_double_sided, build_procedural_mesh,
)

MIN_RELIABLE_REPEATS = 15
THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")
SCENES = (("tiny", {"kind": "fixture", "seed": 1234, "triangles": 1, "size": .03}),
          ("small-triangles", {"kind": "fixture", "seed": 1234, "triangles": 160, "size": .05}),
          ("large-surfaces", {"kind": "fixture", "seed": 1234, "triangles": 8, "size": .8}),
          ("procedural400", {"kind": "procedural", "seed": 991, "rings": 10, "segments": 20}),
          ("procedural5k", {"kind": "procedural", "seed": 991, "rings": 32, "segments": 80}))


class ScalarColorShader(VertexColorShader):
    batch_fragment_equivalent_to = None


def procedural_scene(rings, segments, seed=991):
    vertices, faces = build_procedural_mesh(seed, rings, segments)
    camera = {"yaw_degrees": 25., "pitch_degrees": 20., "center_y": 0.,
              "x_half_extent": 1.6, "y_half_extent": 1.6}
    clip = _camera_transform(vertices, camera)
    faces = _orient_double_sided(clip, faces)
    mesh = [Vertex(v, color=np.asarray([.8, .7, .45], dtype=np.float32)) for v in clip]
    return mesh, [tuple(int(i) for i in face) for face in faces]


def build_scene(spec):
    if spec["kind"] == "fixture":
        if spec["seed"] != 1234:
            raise ValueError("SURFACE_PLAN_FIXTURE_SEED_UNSUPPORTED")
        return make_fixture(spec["triangles"], spec["size"])
    return procedural_scene(spec["rings"], spec["segments"], spec["seed"])


def ablation_policy(scan, force):
    return SurfacePlanPolicy(scan_min_samples=64 if scan else sys.maxsize,
                             draw_min_bbox_samples_per_triangle=0 if force else 64,
                             name="ablation-scan-v1" if scan else "ablation-noscan-v1")


def check_overrides(label, plan, override):
    expected = ablation_policy(**override)
    if (plan is None or plan.get("scan_min_samples") != expected.scan_min_samples
            or plan.get("batch_min_samples") != expected.batch_min_samples
            or plan.get("draw_min_bbox_samples_per_triangle") != expected.draw_min_bbox_samples_per_triangle
            or (override["force"] and plan.get("decision") != "planned")):
        raise AssertionError("SURFACE_PLAN_ABLATION_NOT_APPLIED:" + label)
    if not override["scan"]:
        counts = plan["counts"]
        if counts["corner_edge_evaluations"] != 0 or counts["scan_bypassed"] != plan["binned_pairs"]:
            raise AssertionError("SURFACE_PLAN_ABLATION_NOT_APPLIED:" + label)


def mode_table(ablation, adaptive=False):
    modes = [("tiles", "tiles", FlatShader, None),
             ("plan-scalar", "tiles-plan", ScalarColorShader, None),
             ("plan-batch", "tiles-plan", VertexColorShader, None)]
    if ablation:
        for scan in (False, True):
            for batch in (False, True):
                label = "abl-%s-%s" % ("scan" if scan else "noscan", "batch" if batch else "scalar")
                modes.append((label, "tiles-plan", VertexColorShader if batch else ScalarColorShader,
                              {"scan": scan, "force": True}))
        modes.append(("batch-first", "tiles-plan", VertexColorShader, BATCH_FIRST_POLICY))
    if adaptive:
        modes.append(("adaptive", "tiles-plan", VertexColorShader, ADAPTIVE_PLAN_POLICY))
    return modes


def summarize(values):
    data = np.asarray(values, dtype=float)
    q1, q3 = np.percentile(data, [25, 75])
    median = float(statistics.median(values))
    return {"n": len(values), "median": median, "iqr": float(q3 - q1),
            "mad": float(np.median(np.abs(data - median))),
            "min": float(data.min()), "max": float(data.max())}


def environment():
    cpu = ""
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    try:
        affinity = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity = None
    try:
        config = np.show_config(mode="dicts")
        numpy_build = {key: config.get(key) for key in ("SIMD Extensions", "Build Dependencies")}
    except (TypeError, AttributeError, ValueError):
        numpy_build = None
    return json.loads(json.dumps({
        "cpu_model": cpu or platform.processor() or platform.machine(),
        "logical_cpus": os.cpu_count(), "affinity_cpus": affinity,
        "python_compiler": platform.python_compiler(),
        "thread_env": {key: os.environ.get(key) for key in THREAD_ENV},
        "numpy_build": numpy_build}, default=str))


def measure_scene(name, mesh, faces, size, workers, repeats, ablation=False,
                  deadline=None, spec=None, adaptive=False):
    modes = mode_table(ablation, adaptive=adaptive)
    engines = {}
    times = {label: [] for label, _, _, _ in modes}
    overrides = {label: override for label, _, _, override in modes if isinstance(override, dict)}
    plans = {}
    reference = None
    digest = None
    try:
        for label, backend, shader, override in modes:
            fb = Framebuffer(size, size)
            policy = (override if isinstance(override, SurfacePlanPolicy) else
                      ablation_policy(**override) if override else None)
            engines[label] = (fb, SoftwareRasterizer(fb, backend=backend, num_threads=workers,
                                                    plan_policy=policy), shader())
        for run in range(repeats + 1):
            round_start = time.monotonic()
            # Rotate order to reduce systematic warm-cache/order bias.
            order = list(engines)
            offset = run % len(order)
            for label in order[offset:] + order[:offset]:
                if deadline is not None and time.monotonic() >= deadline:
                    raise RuntimeError("SURFACE_PLAN_BENCHMARK_BUDGET_EXCEEDED:" + name)
                fb, engine, shader = engines[label]
                fb.clear(16, 25, 38, 255, depth=1.0)
                override = overrides.get(label)
                start = time.perf_counter_ns()
                engine.draw_mesh(mesh, faces, shader)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                if deadline is not None and time.monotonic() >= deadline:
                    raise RuntimeError("SURFACE_PLAN_BENCHMARK_BUDGET_EXCEEDED:" + name)
                if run:
                    times[label].append(elapsed)
                image = fb.color_buffer.tobytes() + fb.depth_buffer.tobytes()
                if reference is None:
                    reference = image
                    digest = hashlib.sha256(image).hexdigest()
                elif image != reference:
                    raise AssertionError("SURFACE_PLAN_COLOR_DEPTH_MISMATCH:" + label)
                if override:
                    check_overrides(label, engine.last_plan_receipt, override)
                if label == "batch-first":
                    p = engine.last_plan_receipt
                    if p is None or p.get("policy") != BATCH_FIRST_POLICY.name or any(
                            p.get(key) != getattr(BATCH_FIRST_POLICY, key) for key in (
                                "scan_min_samples", "batch_min_samples", "draw_min_bbox_samples_per_triangle")):
                        raise AssertionError("SURFACE_PLAN_PROFILE_NOT_APPLIED")
                if engine.last_plan_receipt is not None:
                    previous = plans.get(label)
                    if previous is not None and previous != engine.last_plan_receipt:
                        raise AssertionError("SURFACE_PLAN_NOT_DETERMINISTIC")
                    plans[label] = engine.last_plan_receipt
            if run == 0 and deadline is not None:
                # Warm-up round is a conservative per-round estimate; fail fast
                # instead of silently truncating repeats.
                projected = (time.monotonic() - round_start) * repeats
                if time.monotonic() + projected > deadline:
                    raise RuntimeError("SURFACE_PLAN_BENCHMARK_BUDGET_EXCEEDED:" + name)
        medians = {label: statistics.median(values) for label, values in times.items()}
        result = {"scene": name, "triangles": len(faces), "pixels": size,
                  "workers": workers, "repeats": repeats, "byte_identical": True,
                  "image_sha256": digest, "median_frame_ms": medians,
                  "samples_ms": times,
                  "stats_ms": {label: summarize(values) for label, values in times.items()},
                  "speedup_vs_tiles": {label: medians["tiles"] / value
                                       for label, value in medians.items()},
                  "speedup_paired": {label: summarize([base / value for base, value
                                                       in zip(times["tiles"], values)])
                                     for label, values in times.items()},
                  "plans": plans, "gpu_parity_established": False}
        if spec is not None:
            result["scene_spec"] = spec
        if overrides:
            result["ablation"] = overrides
        return result
    finally:
        for _, engine, _ in engines.values():
            engine.executor.shutdown(wait=True)


def write_report(output, receipt):
    """Local, self-contained colored graph projection of actual execution."""
    output.mkdir(parents=True, exist_ok=True)
    (output / "surface-plan-benchmark.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    colors = {"blue": "#2563eb", "purple": "#7c3aed", "orange": "#c2410c", "green": "#15803d"}
    sections = []
    for case in receipt["results"]:
        stats, paired = case["stats_ms"], case["speedup_paired"]
        rows = "".join(
            f"<tr><td>{html.escape(label)}</td><td>{value:.3f}</td>"
            f"<td>{case['speedup_vs_tiles'][label]:.3f}×</td>"
            f"<td>{stats[label]['iqr']:.3f}</td>"
            f"<td>{paired[label]['median']:.3f}×</td></tr>"
            for label, value in case["median_frame_ms"].items())
        plan = case["plans"]["plan-batch"]
        cards = []
        # The trace itself is bounded; render every retained node.
        for node in plan["nodes"]:
            payload = html.escape(json.dumps(node, ensure_ascii=False, indent=2))
            cards.append(f"<details style='border-left:5px solid {colors[node['color']]}'><summary>"
                         f"{html.escape(node['id'])}</summary><pre>{payload}</pre></details>")
        sections.append(f"<section><h2>{html.escape(case['scene'])}</h2>"
                        f"<p>Color + depth: byte-identical. Plan: <code>{plan['plan_sha256']}</code></p>"
                        f"<table><tr><th>Mode</th><th>Median ms</th><th>Relative to tiles</th>"
                        f"<th>IQR ms</th><th>Paired median ratio</th></tr>{rows}</table>"
                        f"<pre>{html.escape(json.dumps(plan['counts'], indent=2))}</pre>"
                        f"<div class='cards'>{''.join(cards)}</div></section>")
    (output / "surface-plan-report.html").write_text(
        "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        "<title>CPU surface-plan evidence</title><style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:1rem}"
        "table{border-collapse:collapse}td,th{padding:.5rem;border:1px solid #aaa;text-align:left}"
        ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:.6rem}"
        "details{padding:.6rem;background:#f1f5f9;overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
        "section{margin:2rem 0}</style><h1>CPU surface-plan evidence</h1>"
        "<p>Blue: math. Purple: sample domain. Orange: observed execution. Green: required contract.</p>"
        "<p>Real same-host CPU runs; timing includes planning and receipts. No hardware-GPU comparison. "
        "Contract labels describe requirements; output parity is checked separately.</p>"
        + "".join(sections) + "</html>\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--pixels", type=int, default=128)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--ablation", action="store_true",
                        help="add forced-plan scan x batch factorial modes")
    parser.add_argument("--adaptive", action="store_true",
                        help="include opt-in deterministic geometry selector")
    parser.add_argument("--max-seconds", type=float, default=1800.,
                        help="subprocess wall-clock budget; 0 disables")
    parser.add_argument("--budget-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (not 1 <= args.repeats <= 30 or not 32 <= args.pixels <= 1024
            or not 1 <= args.workers <= 16 or not math.isfinite(args.max_seconds) or args.max_seconds < 0):
        parser.error("repeats 1-30, pixels 32-1024, workers 1-16, max-seconds >= 0 required")
    if args.max_seconds and not args.budget_child:
        _run_budgeted(args)
        return
    if args.repeats < MIN_RELIABLE_REPEATS:
        print(f"warning: fewer than {MIN_RELIABLE_REPEATS} repeats; borderline cases are not reliable",
              file=sys.stderr)
    deadline = time.monotonic() + args.max_seconds if args.max_seconds else None
    results = []
    for name, spec in SCENES:
        mesh, faces = build_scene(spec)
        results.append(measure_scene(name, mesh, faces, args.pixels, args.workers, args.repeats,
                                     ablation=args.ablation, deadline=deadline, spec=spec,
                                     adaptive=args.adaptive))
        print("SURFACE_PLAN_SCENE_OK:" + name, file=sys.stderr, flush=True)
    receipt = {"protocol": "are.surface-plan-benchmark.v1", "python": platform.python_version(),
               "os": platform.platform(), "numpy": np.__version__,
               "environment": environment(),
               "benchmark_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "fixture_source_sha256": hashlib.sha256(
                   Path(__file__).with_name("compare_tile_backends.py").read_bytes()).hexdigest(),
               "source_paths_sha256": {name: hashlib.sha256(
                   (Path(__file__).resolve().parents[2] / name).read_bytes()).hexdigest()
                   for name in (
                       "software_gpu/benchmarks/compare_surface_plans.py",
                       "software_gpu/benchmarks/compare_tile_backends.py",
                       "software_gpu/integrations/aurion/offline_render_worker.py",
                       *("software_gpu/graphics/" + name for name in (
                           "rasterizer.py", "geometry.py", "tile_backend.py", "surface_plan.py",
                           "framebuffer.py", "batch_shader.py", "shader.py")))},
               "budget_seconds": args.max_seconds,
               "source_sha256": {name: hashlib.sha256(
                   (Path(__file__).resolve().parents[1] / "graphics" / name).read_bytes()).hexdigest()
                   for name in ("rasterizer.py", "geometry.py", "tile_backend.py", "surface_plan.py",
                                "batch_shader.py", "shader.py")},
               "activation": "EXPLICIT_OPT_IN_ONLY", "results": results}
    write_report(args.output_dir, receipt)
    print(json.dumps({"status": "SURFACE_PLAN_BENCHMARK_OK", "results": [
        {k: case[k] for k in ("scene", "byte_identical", "median_frame_ms", "speedup_vs_tiles")}
        for case in results]}, indent=2))


def _run_budgeted(args):
    """Kill a late child and publish completed artifacts only after success."""
    root = Path(__file__).resolve().parents[2]
    destination = args.output_dir.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".surface-plan-", dir=destination.parent) as folder:
        command = [sys.executable, "-m", "software_gpu.benchmarks.compare_surface_plans",
                   "--output-dir", folder, "--repeats", str(args.repeats), "--pixels", str(args.pixels),
                   "--workers", str(args.workers), "--max-seconds", str(args.max_seconds), "--budget-child"]
        if args.ablation:
            command.append("--ablation")
        if args.adaptive:
            command.append("--adaptive")
        try:
            process = subprocess.run(command, cwd=root, timeout=args.max_seconds,
                                     capture_output=True, text=True)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("SURFACE_PLAN_BENCHMARK_BUDGET_EXCEEDED") from exc
        if process.returncode:
            sys.stderr.write(process.stderr)
            if "SURFACE_PLAN_BENCHMARK_BUDGET_EXCEEDED" in process.stderr:
                raise RuntimeError("SURFACE_PLAN_BENCHMARK_BUDGET_EXCEEDED")
            raise RuntimeError("SURFACE_PLAN_BENCHMARK_CHILD_FAILED")
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("surface-plan-benchmark.json", "surface-plan-report.html"):
            os.replace(Path(folder) / name, destination / name)
        sys.stderr.write(process.stderr)
        sys.stdout.write(process.stdout)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
