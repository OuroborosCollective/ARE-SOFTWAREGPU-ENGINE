"""Real CPU A/B: tiles, planned scalar, planned vertex-color batch.

Timings include mesh preparation, classification, shading and graph receipts.
This is a same-host observation, not a GPU comparison or automatic activation.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import platform
import statistics
import time

import numpy as np

from software_gpu.benchmarks.compare_tile_backends import FlatShader, make_fixture
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex
from software_gpu.integrations.aurion.offline_render_worker import (
    _camera_transform, _orient_double_sided, build_procedural_mesh,
)


class ScalarColorShader(VertexColorShader):
    batch_fragment_equivalent_to = None


def procedural_scene(rings, segments):
    vertices, faces = build_procedural_mesh(991, rings, segments)
    camera = {"yaw_degrees": 25., "pitch_degrees": 20., "center_y": 0.,
              "x_half_extent": 1.6, "y_half_extent": 1.6}
    clip = _camera_transform(vertices, camera)
    faces = _orient_double_sided(clip, faces)
    mesh = [Vertex(v, color=np.asarray([.8, .7, .45], dtype=np.float32)) for v in clip]
    return mesh, [tuple(int(i) for i in face) for face in faces]


def measure_scene(name, mesh, faces, size, workers, repeats):
    modes = (("tiles", "tiles", FlatShader()),
             ("plan-scalar", "tiles-plan", ScalarColorShader()),
             ("plan-batch", "tiles-plan", VertexColorShader()))
    engines = {}
    times = {name: [] for name, _, _ in modes}
    plans = {}
    reference = None
    digest = None
    try:
        for label, backend, shader in modes:
            fb = Framebuffer(size, size)
            engines[label] = (fb, SoftwareRasterizer(fb, backend=backend, num_threads=workers), shader)
        for run in range(repeats + 1):
            # Rotate order to reduce systematic warm-cache/order bias.
            order = list(engines)
            offset = run % len(order)
            for label in order[offset:] + order[:offset]:
                fb, engine, shader = engines[label]
                fb.clear(16, 25, 38, 255, depth=1.0)
                start = time.perf_counter_ns()
                engine.draw_mesh(mesh, faces, shader)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                if run:
                    times[label].append(elapsed)
                image = fb.color_buffer.tobytes() + fb.depth_buffer.tobytes()
                if reference is None:
                    reference = image
                    digest = hashlib.sha256(image).hexdigest()
                elif image != reference:
                    raise AssertionError("SURFACE_PLAN_COLOR_DEPTH_MISMATCH:" + label)
                if engine.last_plan_receipt is not None:
                    previous = plans.get(label)
                    if previous is not None and previous != engine.last_plan_receipt:
                        raise AssertionError("SURFACE_PLAN_NOT_DETERMINISTIC")
                    plans[label] = engine.last_plan_receipt
        medians = {label: statistics.median(values) for label, values in times.items()}
        return {"scene": name, "triangles": len(faces), "pixels": size,
                "workers": workers, "repeats": repeats, "byte_identical": True,
                "image_sha256": digest, "median_frame_ms": medians,
                "samples_ms": times,
                "speedup_vs_tiles": {label: medians["tiles"] / value
                                     for label, value in medians.items()},
                "plans": plans, "gpu_parity_established": False}
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
        rows = "".join(
            f"<tr><td>{html.escape(label)}</td><td>{value:.3f}</td>"
            f"<td>{case['speedup_vs_tiles'][label]:.3f}×</td></tr>"
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
                        f"<table><tr><th>Mode</th><th>Median ms</th><th>Relative to tiles</th></tr>{rows}</table>"
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
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 10 or not 32 <= args.pixels <= 512 or not 1 <= args.workers <= 16:
        parser.error("repeats 1-10, pixels 32-512, workers 1-16 required")
    cases = [("tiny", *make_fixture(1, .03)),
             ("small-triangles", *make_fixture(160, .05)),
             ("large-surfaces", *make_fixture(8, .8)),
             ("procedural400", *procedural_scene(10, 20)),
             ("procedural5k", *procedural_scene(32, 80))]
    results = [measure_scene(name, mesh, faces, args.pixels, args.workers, args.repeats)
               for name, mesh, faces in cases]
    receipt = {"protocol": "are.surface-plan-benchmark.v1", "python": platform.python_version(),
               "os": platform.platform(), "numpy": np.__version__,
               "source_sha256": {name: hashlib.sha256(
                   (Path(__file__).resolve().parents[1] / "graphics" / name).read_bytes()).hexdigest()
                   for name in ("rasterizer.py", "geometry.py", "tile_backend.py", "surface_plan.py",
                                "batch_shader.py", "shader.py")},
               "activation": "EXPLICIT_OPT_IN_ONLY", "results": results}
    write_report(args.output_dir, receipt)
    print(json.dumps({"status": "SURFACE_PLAN_BENCHMARK_OK", "results": [
        {k: case[k] for k in ("scene", "byte_identical", "median_frame_ms", "speedup_vs_tiles")}
        for case in results]}, indent=2))


if __name__ == "__main__":
    main()
