"""External *real* CPU raster benchmark: ARE bands/tiles/JIT vs Mesa llvmpipe.

This is a research harness, not a performance marketing claim. All backends
render the same SHA-256-identified geometry, on the same host in separate
processes. Mesa must identify itself as llvmpipe; GPU fallback is rejected.
Differences in shader implementations, clip rules, depth and MSAA sampling
are explicitly recorded. No speedup is published for noncomparable output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time

import numpy as np

PROTOCOL = "are.external-cpu-render-bench.v1"
SCENES = ("micro", "overdraw", "game", "near_clip", "msaa4")
BACKENDS = ("bands", "tiles", "tiles-jit", "llvmpipe")
PALETTE = np.array([[1.0, .25, .25], [.25, 1.0, .25],
                    [.25, .25, 1.0], [.75, .75, .25]], dtype=np.float32)


def scene_data(scene: str):
    """Exact geometry array [x,y,z,r,g,b] shared by CPU and OpenGL backends."""
    if scene not in SCENES:
        raise ValueError("UNSUPPORTED_SCENE")
    settings = {
        "micro": (96, 48, .065),
        "overdraw": (96, 16, .74),
        "game": (160, 96, .09),
        "near_clip": (96, 8, .64),
        "msaa4": (64, 4, .70),
    }
    size, count, radius = settings[scene]
    rng = np.random.default_rng(904 + SCENES.index(scene))
    vertices = []
    for i in range(count):
        if scene == "overdraw":
            cx, cy = rng.uniform(-.25, .25, 2)
        else:
            cx, cy = rng.uniform(-.85, .85, 2)
        z = (-1.35 if scene == "near_clip" and i % 3 == 0
             else float((-.64, -.24, .12, .51)[i % 4]))
        points = ((cx-radius, cy-radius, z),
                  (cx+radius, cy-radius, z),
                  (cx, cy+radius, z))
        # Flat per-primitive palette: identical fragment *function* in each
        # implementation, and no interpolated-attribute shader mismatch.
        color = PALETTE[i % len(PALETTE)]
        for point in points:
            vertices.append([*point, *color])
    array = np.ascontiguousarray(vertices, dtype="<f4")
    digest = hashlib.sha256(array.tobytes()).hexdigest()
    return size, array, digest


class FlatShader:
    def vertex_shader(self, vertex):
        return vertex.position, {"color": vertex.color}

    def fragment_shader(self, varyings):
        channels = (np.clip(varyings["color"], 0, 1) * 255).astype(np.uint8)
        return int(channels[0]), int(channels[1]), int(channels[2]), 255


def _measure(draw, repeats):
    """First-call (incl. JIT), warm-ups and steady-state perf_counter timings."""
    warmup_ms = []
    for _ in range(2):
        start = time.perf_counter_ns()
        draw()
        warmup_ms.append((time.perf_counter_ns() - start) / 1e6)
    wall_ms, cpu_ms = [], []
    for _ in range(repeats):
        cpu_start, wall_start = time.process_time_ns(), time.perf_counter_ns()
        draw()
        wall_ms.append((time.perf_counter_ns() - wall_start) / 1e6)
        cpu_ms.append((time.process_time_ns() - cpu_start) / 1e6)
    return {
        "first_call_ms_includes_initialization": round(warmup_ms[0], 4),
        "second_warmup_ms": round(warmup_ms[1], 4),
        "wall_samples_ms": [round(x, 4) for x in wall_ms],
        "process_cpu_samples_ms": [round(x, 4) for x in cpu_ms],
        "wall_median_ms": round(statistics.median(wall_ms), 4),
        "wall_p95_ms": round(float(np.percentile(wall_ms, 95)), 4),
        "process_cpu_median_ms": round(statistics.median(cpu_ms), 4),
        "repeats": repeats,
    }


def _peak_memory():
    # On Linux resource.ru_maxrss is KiB, and is a cumulative process peak.
    if platform.system() != "Linux":
        return None
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _bench_are(backend, scene, repeats, workers, size, data):
    from software_gpu.graphics.shader import Vertex
    from software_gpu.graphics.rasterizer import SoftwareRasterizer
    from software_gpu.graphics.framebuffer import Framebuffer
    from software_gpu.graphics.postprocess import MSAARasterizer, MSAAFramebuffer

    verts = [Vertex(row[:3], color=row[3:]) for row in data]
    faces = [(i, i + 1, i + 2) for i in range(0, len(verts), 3)]
    shader = FlatShader()
    if scene == "msaa4":
        fb = MSAAFramebuffer(size, size, samples=4)
        stage = MSAARasterizer(fb)
        def draw():
            fb.clear(0, 0, 0, 255, depth=1.0)
            stage.draw_mesh(verts, faces, shader)
            fb.resolve()
        try:
            timing = _measure(draw, repeats)
            rgba = fb.resolve().color_buffer.copy()
        finally:
            pass
        return timing, rgba, {"engine": "ARE CPU 4x MSAA", "backend": "msaa4",
                              "fragmentLanguage": "Python",
                              "samplePattern": "fixed 2x2 .25/.75"}
    fb = Framebuffer(size, size)
    engine = SoftwareRasterizer(fb, backend=backend, tile_size=16, num_threads=workers)
    try:
        def draw():
            fb.clear(0, 0, 0, 255, depth=1.0)
            engine.draw_mesh(verts, faces, shader)
        timing = _measure(draw, repeats)
        rgba = fb.color_buffer.copy()
    finally:
        engine.executor.shutdown(wait=True)
    return timing, rgba, {"engine": "ARE CPU raster", "backend": backend,
                          "fragmentLanguage": "Python",
                          "samplePattern": "pixel center"}


def _bench_mesa(scene, repeats, workers, size, data):
    import moderngl

    # This identity assertion makes a host GPU or another software driver a
    # hard UNSUPPORTED outcome, never silently mislabeled as llvmpipe.
    ctx = moderngl.create_standalone_context(require=330, backend="egl")
    info = ctx.info
    renderer = str(info.get("GL_RENDERER", ""))
    if "llvmpipe" not in renderer.lower():
        raise RuntimeError("UNSUPPORTED_MESA_RENDERER_NOT_LLVMPIPE")
    ctx.enable_only(moderngl.DEPTH_TEST)
    ctx.depth_func = "<"
    program = ctx.program(
        vertex_shader="#version 330\nin vec3 in_position;\nin vec3 in_color;\n"
                      "out vec3 v_color;\nvoid main(){gl_Position=vec4(in_position,1.0);"
                      "v_color=in_color;}",
        fragment_shader="#version 330\nin vec3 v_color;\nout vec4 fragColor;\n"
                        "void main(){vec3 rgb=floor(clamp(v_color,0.0,1.0)"
                        "*255.0)/255.0;fragColor=vec4(rgb,1.0);}",
    )
    vbo = ctx.buffer(data.tobytes())
    vao = ctx.vertex_array(program, [(vbo, "3f 3f", "in_position", "in_color")])
    is_msaa = scene == "msaa4"
    if is_msaa:
        msaa_color = ctx.renderbuffer((size, size), components=4, samples=4)
        msaa_depth = ctx.depth_renderbuffer((size, size), samples=4)
        target = ctx.framebuffer(color_attachments=[msaa_color],
                                 depth_attachment=msaa_depth)
        resolved_color = ctx.texture((size, size), components=4, dtype="f1")
        resolved = ctx.framebuffer(color_attachments=[resolved_color])
        sampler_name = "mesa-implementation-defined-4x"
    else:
        color = ctx.texture((size, size), components=4, dtype="f1")
        depth = ctx.depth_renderbuffer((size, size))
        target = ctx.framebuffer(color_attachments=[color], depth_attachment=depth)
        resolved = target
        sampler_name = "pixel center"
    ctx.viewport = (0, 0, size, size)
    try:
        def draw():
            target.use()
            target.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
            # Including a fresh VBO upload offsets some of the ARE geometry
            # preprocessing; it does NOT make both pipelines equal in scope.
            vbo.write(data.tobytes())
            vao.render(mode=moderngl.TRIANGLES, vertices=len(data))
            if is_msaa:
                ctx.copy_framebuffer(resolved, target)
            ctx.finish()
        timing = _measure(draw, repeats)
        rgba = np.frombuffer(resolved.read(components=4, alignment=1),
                             dtype=np.uint8).reshape((size, size, 4))[::-1].copy()
        descriptor = {"engine": "Mesa llvmpipe (software OpenGL)",
                      "backend": "llvmpipe",
                      "fragmentLanguage": "GLSL 330 compiled through Mesa",
                      "samplePattern": sampler_name,
                      "GL_RENDERER": renderer,
                      "GL_VENDOR": info.get("GL_VENDOR", ""),
                      "GL_VERSION": info.get("GL_VERSION", ""),
                      "LP_NUM_THREADS_requested": workers}
        return timing, rgba, descriptor
    finally:
        ctx.release()


def child_run(args):
    size, data, scene_sha = scene_data(args.scene)
    try:
        if args.backend == "llvmpipe":
            timing, rgba, details = _bench_mesa(args.scene, args.repeats, args.workers, size, data)
        else:
            timing, rgba, details = _bench_are(args.backend, args.scene, args.repeats,
                                               args.workers, size, data)
        np.save(args.image_output, rgba, allow_pickle=False)
        evidence = {
            "protocol": PROTOCOL, "status": "MEASURED",
            "scene": args.scene, "scene_sha256": scene_sha,
            "resolution": size, "triangles": len(data) // 3,
            "backend": args.backend if args.scene != "msaa4" or args.backend == "llvmpipe" else "msaa4",
            "workers_requested": args.workers,
            "timing": timing, "details": details,
            "image_sha256": hashlib.sha256(rgba.tobytes()).hexdigest(),
            "image_shape": list(rgba.shape),
            "peak_rss_bytes_linux_process": _peak_memory(),
            "energy_status": "UNAVAILABLE_NO_ENERGY_METER",
            "input_upload_scope": ("fresh VBO upload + clear + draw + GPU finish"
                                   if args.backend == "llvmpipe"
                                   else "clear + CPU geometry, shading and framebuffer write"),
        }
        return evidence, 0
    except Exception as exc:
        reason = str(exc)
        unsupported = (args.backend == "llvmpipe" and
                       (isinstance(exc, (ImportError, OSError)) or
                        reason.startswith("UNSUPPORTED_") or
                        "Cannot find supported backend" in reason or
                        "cannot create context" in reason.lower()))
        evidence = {
            "protocol": PROTOCOL, "status": "UNSUPPORTED" if unsupported else "ERROR",
            "backend": args.backend, "scene": args.scene,
            "scene_sha256": scene_sha, "workers_requested": args.workers,
            "failure_type": type(exc).__name__,
            # No exception body or credentials are echoed.
            "failure_family": ("MESA_UNAVAILABLE_OR_UNVERIFIED"
                               if unsupported else "BENCHMARK_EXECUTION_FAILED"),
        }
        return evidence, 2


def compare_images(are, mesa, scene):
    """Color and coverage comparison; intentionally no fake depth equivalence."""
    if are.shape != mesa.shape or are.dtype != np.uint8 or mesa.dtype != np.uint8:
        raise ValueError("MISMATCHED_READBACK_FORMAT")
    diff = np.abs(are[..., :3].astype(np.int16) - mesa[..., :3].astype(np.int16))
    are_coverage = np.any(are[..., :3] != 0, axis=2)
    mesa_coverage = np.any(mesa[..., :3] != 0, axis=2)
    union = np.logical_or(are_coverage, mesa_coverage)
    overlap = np.logical_and(are_coverage, mesa_coverage)
    if not union.any():
        raise ValueError("UNVERIFIED_EMPTY_RENDER_OUTPUT")
    diff_max = int(diff.max())
    ratio_off = float(np.count_nonzero(np.any(diff > 2, axis=2))) / union.size
    coverage_iou = float(overlap.sum()) / float(union.sum())
    result = {
        "coverage_iou": round(coverage_iou, 6),
        "rgb_max_absolute_error": diff_max,
        "rgb_mae": round(float(diff.mean()), 6),
        "pixels_with_channel_error_over_2": int(np.count_nonzero(np.any(diff > 2, axis=2))),
        "fraction_pixels_with_channel_error_over_2": round(ratio_off, 6),
        "depth_readback": "UNVERIFIED",
        "msaa_sample_positions": ("NOT_COMPARABLE" if scene == "msaa4" else "not_applicable"),
    }
    # Identical workload specification != identical shader implementation.
    # Only same-sample-color-parity cases may have a clearly caveated ratio.
    comparable = scene != "msaa4" and coverage_iou >= .995 and ratio_off <= .01
    result["classification"] = ("SCENE_COLOR_PARITY_WITH_TOLERANCE"
                                if comparable else
                                "NOT_COMPARABLE_MSAA_SAMPLE_POSITIONS" if scene == "msaa4"
                                else "NOT_COMPARABLE_OUTPUT_DIFFERENCE")
    return result


def _backend_order(args):
    return ("bands", "tiles", "tiles-jit", "llvmpipe") if args.jit else ("bands", "tiles", "llvmpipe")


def orchestrate(args):
    if not (1 <= args.workers <= 8 and 3 <= args.repeats <= 25):
        raise ValueError("workers must be 1..8, repeats must be 3..25")
    os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
    os.environ["GALLIUM_DRIVER"] = "llvmpipe"
    os.environ["EGL_PLATFORM"] = "surfaceless"
    results = []
    hard_failures = []
    with tempfile.TemporaryDirectory(prefix="are-real-cpu-comparison-") as temp:
        for scene in SCENES:
            samples = {}
            for backend in _backend_order(args):
                image = Path(temp) / f"{scene}-{backend}.npy"
                command = [sys.executable, "-m", "software_gpu.benchmarks.external_cpu_benchmark",
                           "--child", "--scene", scene, "--backend", backend,
                           "--workers", str(args.workers), "--repeats", str(args.repeats),
                           "--image-output", str(image)]
                env = dict(os.environ)
                env["LP_NUM_THREADS"] = str(args.workers)
                env["OMP_NUM_THREADS"] = str(args.workers)
                env["OPENBLAS_NUM_THREADS"] = "1"
                proc = subprocess.run(command, text=True, capture_output=True,
                                      timeout=180, env=env, check=False)
                try:
                    sample = json.loads(proc.stdout.splitlines()[-1])
                except (ValueError, IndexError):
                    sample = {"protocol": PROTOCOL, "status": "ERROR",
                              "failure_family": "CHILD_INVALID_EVIDENCE"}
                if (sample.get("protocol") != PROTOCOL or sample.get("scene") != scene or
                    sample.get("backend") not in (backend, "msaa4") or
                    sample.get("workers_requested") != args.workers):
                    sample = {"protocol": PROTOCOL, "status": "ERROR",
                              "failure_family": "CHILD_CONTRACT_VIOLATION"}
                if proc.returncode != 0 and sample.get("status") == "MEASURED":
                    sample = {"protocol": PROTOCOL, "status": "ERROR",
                              "failure_family": "CHILD_EXIT_INCONSISTENT"}
                if sample.get("status") == "MEASURED":
                    size, _, digest = scene_data(scene)
                    if sample.get("scene_sha256") != digest or sample.get("resolution") != size:
                        sample = {"protocol": PROTOCOL, "status": "ERROR",
                                  "failure_family": "CHILD_SOURCE_HASH_MISMATCH"}
                    elif not image.is_file():
                        sample = {"protocol": PROTOCOL, "status": "ERROR",
                                  "failure_family": "CHILD_MISSING_IMAGE"}
                    else:
                        pixels = np.load(image, allow_pickle=False)
                        if hashlib.sha256(pixels.tobytes()).hexdigest() != sample["image_sha256"]:
                            sample = {"protocol": PROTOCOL, "status": "ERROR",
                                      "failure_family": "CHILD_IMAGE_HASH_MISMATCH"}
                        else:
                            samples[backend] = pixels
                if sample.get("status") != "MEASURED":
                    hard_failures.append(f"{scene}/{backend}: {sample.get('failure_family', 'UNKNOWN')}")
                results.append(sample)
            mesa = samples.get("llvmpipe")
            cpu_baseline = samples.get("bands")
            if cpu_baseline is not None:
                for backend in ("tiles", "tiles-jit"):
                    if backend in samples and not np.array_equal(cpu_baseline, samples[backend]):
                        hard_failures.append(f"{scene}/{backend}: ARE_BACKEND_IMAGE_PARITY_FAILED")
            if mesa is not None:
                for backend in ("bands", "tiles", "tiles-jit"):
                    if backend in samples:
                        match = compare_images(samples[backend], mesa, scene)
                        for result in results:
                            if result.get("scene") == scene and result.get("backend") == (backend if scene != "msaa4" else "msaa4"):
                                result["mesa_color_comparison"] = match
                                result["observed_llvmpipe_to_are_wall_ratio"] = None
                                if match["classification"] == "SCENE_COLOR_PARITY_WITH_TOLERANCE":
                                    mesa_t = next(x["timing"]["wall_median_ms"] for x in results
                                                  if x.get("scene") == scene and x.get("backend") == "llvmpipe"
                                                  and x.get("status") == "MEASURED")
                                    cpu_t = result["timing"]["wall_median_ms"]
                                    result["observed_llvmpipe_to_are_wall_ratio"] = round(mesa_t / cpu_t, 4)
    # Each ratio is ONLY same-host and same-sample comparison. Never aggregate
    # different GitHub hosts and never call it a GPU-replacement speedup.
    output = {
        "protocol": PROTOCOL,
        "source_revision": os.getenv("GITHUB_SHA", "local"),
        "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "platform": platform.platform(),
        "cpu_architecture": platform.machine(),
        "cpu_model_linux": (next((line.split(":", 1)[1].strip()
                                  for line in Path("/proc/cpuinfo").read_text().splitlines()
                                  if line.startswith("model name")), "unknown")
                            if Path("/proc/cpuinfo").exists() else "unavailable"),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "workers_requested": args.workers,
        "repeats": args.repeats,
        "benchmark_scope": "separate processes, same host, differing software stacks",
        "direct_gpu_dependency": False,
        "llvmpipe_forced": True,
        "warp": "UNSUPPORTED_NOT_EXECUTED",
        "energy": "UNAVAILABLE_NO_ENERGY_METER",
        "results": results,
        "hard_failures": hard_failures,
        "mutationAuthority": "none",
    }
    encoded = json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    output["receipt_sha256"] = hashlib.sha256(encoded).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, sort_keys=True, indent=2, allow_nan=False)+"\n",
                           encoding="utf-8")
    stats = {"total": len(results), "measured": sum(x.get("status") == "MEASURED" for x in results),
             "failures": hard_failures, "file": str(args.output),
             "receipt_sha256": output["receipt_sha256"]}
    print("EXTERNAL_CPU_BENCHMARK_RESULT " + json.dumps(stats, sort_keys=True))
    if hard_failures:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--jit", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("external-cpu-benchmark.json"))
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scene", choices=SCENES, help=argparse.SUPPRESS)
    parser.add_argument("--backend", choices=BACKENDS, help=argparse.SUPPRESS)
    parser.add_argument("--image-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        if not args.scene or not args.backend or args.image_output is None:
            parser.error("child arguments incomplete")
        evidence, code = child_run(args)
        print(json.dumps(evidence, sort_keys=True, allow_nan=False))
        raise SystemExit(code)
    orchestrate(args)


if __name__ == "__main__":
    main()
