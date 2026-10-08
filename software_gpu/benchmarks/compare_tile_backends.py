"""Reference-vs-tile end-to-end CPU graphics benchmark with output parity.

Uses actual mesh submission and real fragment shading; does not claim DirectX,
CUDA or GPU hardware performance. Numbers are per-machine observations only.
"""
import argparse
from importlib.util import find_spec
import json
import platform
import statistics
import time

import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Shader, Vertex


class FlatShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {"color": vertex.color}

    def fragment_shader(self, varyings):
        color = np.clip(varyings["color"] * 255, 0, 255).astype(np.uint8)
        return int(color[0]), int(color[1]), int(color[2]), 255


def make_fixture(count, radius):
    rng = np.random.default_rng(1234)
    vertices, indices = [], []
    for _ in range(count):
        cx, cy = rng.uniform(-.95, .95, 2)
        z = rng.uniform(.05, .85)
        points = ((cx-radius, cy-radius, z),
                  (cx+radius, cy-radius, z),
                  (cx, cy+radius, z))
        start = len(vertices)
        color = rng.uniform(.15, 1.0, 3).astype(np.float32)
        vertices.extend(Vertex(np.array(p, dtype=np.float32), color=color) for p in points)
        indices.append((start, start+1, start+2))
    return vertices, indices


def measure(size, count, radius, workers, tile_size, repeats, jit):
    vertices, indices = make_fixture(count, radius)
    shader = FlatShader()
    results, outputs = {}, {}
    for backend in ("bands", "tiles", "tiles-jit") if jit else ("bands", "tiles"):
        fb = Framebuffer(size, size)
        engine = SoftwareRasterizer(fb, tile_size=tile_size,
                                    num_threads=workers, backend=backend)
        times = []
        try:
            for run in range(repeats + 1):
                fb.clear(0, 0, 0, 255, 1.0)
                start = time.perf_counter_ns()
                engine.draw_mesh(vertices, indices, shader)
                elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000.0
                if run:
                    times.append(elapsed_ms)
            results[backend] = round(statistics.median(times), 3)
            outputs[backend] = (fb.color_buffer.copy(), fb.depth_buffer.copy())
        finally:
            engine.executor.shutdown(wait=True)
    baseline = outputs["bands"]
    parity = {}
    for backend, (color, depth) in outputs.items():
        color_equal = np.array_equal(color, baseline[0])
        max_depth_error = float(np.max(np.abs(depth - baseline[1])))
        parity[backend] = {"color_equal": bool(color_equal),
                           "max_depth_error": max_depth_error}
        if not color_equal or max_depth_error > 1e-6:
            raise AssertionError("Image/depth parity regression: " + backend)
    return {
        "resolution": size,
        "triangles": count,
        "triangle_radius": radius,
        "workers": workers,
        "tile_size": tile_size,
        "median_frame_ms": results,
        "relative_to_bands": {b: round(results["bands"] / max(t, 1e-10), 3)
                              for b, t in results.items()},
        "reference_parity": parity,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--tile-size", type=int, default=32)
    parser.add_argument("--jit", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 30 or args.workers < 1 or args.workers > 64:
        parser.error("repeats must be 1-30 and workers must be 1-64")
    if args.jit and find_spec("numba") is None:
        parser.error("--jit requires the optional software_gpu[jit] dependency")
    cases = ((128, 160, .05), (128, 8, .8), (256, 320, .045))
    samples = [measure(size, count, radius, args.workers, args.tile_size,
                       args.repeats, args.jit) for size, count, radius in cases]
    print(json.dumps({
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "jit": bool(args.jit),
        "results": samples,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
