"""#285 opt-in material profiles: real complete CPU-frame A/B receipts.

This intentionally reports COST and DIFFERENT semantics, not a speedup or FPS.
No automatic ranking promotion. Local host/CPU/affinity are recorded; no GPU.
"""
import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time

import numpy as np
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.render_profiles import OptInCpuRenderer, frame_receipt
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex


class _Color:
    def __init__(self, rgba):
        self.rgba = rgba

    def vertex_shader(self, vertex):
        return np.asarray(vertex.position, dtype=np.float64), {}

    def fragment_shader(self, varying):
        return self.rgba


def _frame(profile, pixels):
    fb = Framebuffer(pixels, pixels)
    fb.clear(0, 0, 0, 255, depth=1.0)
    vertices = [Vertex(np.array([x, y, 0.4, 1.0]))
                for x, y in ((-0.75, -0.75), (0.75, -0.75), (0.0, 0.75))]
    faces = [(0, 1, 2)]
    if profile == "legacy":
        raster = SoftwareRasterizer(fb, num_threads=1, tile_size=16, backend="tiles")
        try:
            raster.draw_mesh(vertices, faces, _Color((255, 0, 0, 255)))
        finally:
            raster.executor.shutdown(wait=True)
    else:
        with OptInCpuRenderer(fb, tile_size=16, workers=1) as raster:
            if profile == "alpha-test":
                raster.draw_alpha_test(vertices, faces, _Color((255, 0, 0, 255)))
            elif profile == "blend":
                raster.blend_sorted([(0.4, vertices, faces, _Color((255, 0, 0, 128)))])
            elif profile == "shadow":
                light = np.eye(4)
                shadow = raster.make_shadow_map([(vertices, faces)], light, resolution=pixels)
                from software_gpu.graphics.render_profiles import ShadowedShader
                caster = vertices
                raster.draw_opaque(caster, faces,
                                   ShadowedShader(_Color((255, 0, 0, 255)), shadow))
            else:
                raise ValueError("PROFILE_UNSUPPORTED")
    return fb


def measure(pixels, pairs):
    if type(pixels) is not int or not 32 <= pixels <= 512:
        raise ValueError("PIXELS_INVALID")
    if type(pairs) is not int or pairs < 15 or pairs > 100:
        raise ValueError("PAIRS_INVALID")
    profiles = ("legacy", "alpha-test", "blend", "shadow")
    raw = {x: [] for x in profiles}
    fingerprints = {}
    # A/B order alternates, and the whole frame includes clear, setup,
    # draw(s), optional shadow pass and worker teardown.
    for pair in range(pairs):
        order = profiles if pair % 2 == 0 else tuple(reversed(profiles))
        for profile in order:
            start = time.perf_counter_ns()
            fb = _frame(profile, pixels)
            elapsed = time.perf_counter_ns() - start
            raw[profile].append(elapsed / 1e6)
            receipt = frame_receipt(fb, profile, "issue285-triangle")
            prior = fingerprints.get(profile)
            if prior is not None and (
                    prior["rgba_sha256"] != receipt["rgba_sha256"] or
                    prior["depth_sha256"] != receipt["depth_sha256"]):
                raise ValueError("FRAME_FINGERPRINT_DRIFT")
            fingerprints[profile] = receipt
    info = {
        "protocol": "are.optin-cpu-material-cost.v1",
        "no_fps_or_gpu_claim": True,
        "head_sha": next(iter(fingerprints.values()))["head_sha"],
        "host": {"system": platform.system(), "machine": platform.machine(),
                 "processor": platform.processor(), "python": sys.version,
                 "numpy": np.__version__,
                 "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                 "cpu_count": os.cpu_count()},
        "pixels": pixels, "scene": "issue285-triangle",
        "pairs": pairs,
        "timings_ms": {key: {"raw": values, "median": statistics.median(values),
                              "iqr": (np.percentile(values, 75) - np.percentile(values, 25)).item()}
                       for key, values in raw.items()},
        "full_frame_fingerprints": fingerprints,
        "semantics_comparable": {
            "legacy_vs_alpha_test": fingerprints["legacy"]["rgba_sha256"] ==
                                    fingerprints["alpha-test"]["rgba_sha256"] and
                                    fingerprints["legacy"]["depth_sha256"] ==
                                    fingerprints["alpha-test"]["depth_sha256"],
            "legacy_vs_blend": False, "legacy_vs_shadow": False},
    }
    data = json.dumps(info, sort_keys=True, separators=(",", ":"), allow_nan=False)
    info["sha256"] = hashlib.sha256(data.encode("utf-8")).hexdigest()
    return info


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pixels", type=int, default=64)
    parser.add_argument("--pairs", type=int, default=15)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = measure(args.pixels, args.pairs)
    with open(args.output, "x", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")
    print("Saved full-frame CPU cost receipt (no FPS/GPU claim):", args.output)
