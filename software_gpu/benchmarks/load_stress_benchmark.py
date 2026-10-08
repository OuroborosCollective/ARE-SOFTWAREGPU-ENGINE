"""
Dynamic Load & Stress Benchmark Suite for SoftwareGPU.
Measures real FPS under executing load for both GPGPU Compute and 3D Graphics,
calculates the performance degradation curve (Abfallkurve), saturation points, and final score.
"""

import time
import json
import math
import numpy as np

from software_gpu.core.device import VirtualGPU
from software_gpu.core.vps_governor import VPSHardwareGovernor
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Vertex, BlinnPhongShader, Matrix4
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.compute.kernels import VectorizedGPUKernels


def generate_stress_mesh(rings: int, sectors: int) -> tuple:
    """Generates a parametric 3D mesh with scalable triangle density."""
    vertices = []
    indices = []
    R = 1.0

    for r in range(rings + 1):
        theta = math.pi * float(r) / float(rings)
        y = R * math.cos(theta)
        r_slice = R * math.sin(theta)

        for s in range(sectors + 1):
            phi = 2.0 * math.pi * float(s) / float(sectors)
            x = r_slice * math.sin(phi)
            z = r_slice * math.sin(phi)

            vertices.append(Vertex(
                position=np.array([x, y, z], dtype=np.float32),
                normal=np.array([x / R, y / R, z / R], dtype=np.float32),
                color=np.array([0.3, 0.6, 0.9], dtype=np.float32)
            ))

    for r in range(rings):
        for s in range(sectors):
            first = r * (sectors + 1) + s
            second = first + sectors + 1
            indices.append((first, second, first + 1))
            indices.append((second, second + 1, first + 1))

    return vertices, indices


def run_load_stress_benchmark():
    device = VirtualGPU.get_current_device()
    governor = VPSHardwareGovernor()
    gov_status = governor.get_status_report()

    print("=" * 75)
    print(" SoftwareGPU Load Stress Benchmark & Performance Degradation Analysis")
    print(f" Hardware: {device.properties.name}")
    print(f" Detected VPS Effective Cores: {gov_status['effective_cpu_cores']}")
    print(f" Recommended Safe Concurrency: {gov_status['recommended_safe_workers']} Threads ({gov_status['headroom_percentage']} Headroom)")
    print("=" * 75)

    # =============================================================
    # Part 1: GPGPU Compute Stress Benchmark (GEMM Workloads)
    # =============================================================
    print("\n[PART 1: GPGPU Compute Scaling & FPS under Increasing Matrix Load]")
    print(f"{'Stage':<6} {'Matrix Size':<14} {'GFLOPs Req.':<14} {'Latency':<12} {'Compute FPS':<14} {'GFLOPS Achieved'}")
    print("-" * 75)

    compute_stages = [
        {"stage": 1, "size": 64},
        {"stage": 2, "size": 128},
        {"stage": 3, "size": 256},
        {"stage": 4, "size": 512},
        {"stage": 5, "size": 768},
        {"stage": 6, "size": 1024},
    ]

    compute_results = []
    for cs in compute_stages:
        N = cs["size"]
        A = np.random.randn(N, N).astype(np.float32)
        B = np.random.randn(N, N).astype(np.float32)
        d_a = device.memory.to_device(A)
        d_b = device.memory.to_device(B)
        d_c = device.memory.allocate((N, N), dtype=np.float32)

        # Warm-up
        VectorizedGPUKernels.gemm_parallel(d_a, d_b, d_c)

        # Measurement iterations
        iters = 5
        times = []
        for _ in range(iters):
            t0 = time.perf_counter()
            VectorizedGPUKernels.gemm_parallel(d_a, d_b, d_c)
            times.append(time.perf_counter() - t0)

        avg_lat = np.mean(times)
        fps = 1.0 / avg_lat if avg_lat > 0 else 0.0
        total_ops = 2.0 * (N ** 3)
        gflops = (total_ops / avg_lat) / 1e9

        compute_results.append({
            "stage": cs["stage"],
            "matrix_size": f"{N}x{N}",
            "latency_ms": avg_lat * 1000.0,
            "fps": fps,
            "gflops": gflops
        })

        print(f"{cs['stage']:<6} {f'{N}x{N}':<14} {total_ops/1e6:>8.2f} MFLOP  {avg_lat * 1000.0:>8.2f} ms   {fps:>10,.1f} FPS   {gflops:>10.2f} GFLOPS")

        device.memory.free(d_a)
        device.memory.free(d_b)
        device.memory.free(d_c)

    # Compute Degradation Curve
    print("\n[Compute Throughput Curve - GFLOPS under Load]:")
    max_gflops = max(r["gflops"] for r in compute_results)
    for r in compute_results:
        bar_len = int((r["gflops"] / max_gflops) * 35) if max_gflops > 0 else 0
        bar = "█" * bar_len + "░" * (35 - bar_len)
        print(f" {r['matrix_size']:>9}: [{bar}] {r['gflops']:>6.1f} GFLOPS ({r['fps']:>7,.0f} FPS, {r['latency_ms']:>6.2f} ms)")

    # =============================================================
    # Part 2: 3D Graphics Software Rasterization Stress Test
    # =============================================================
    print("\n[PART 2: 3D Graphics Rasterization & Blinn-Phong FPS under Geometric Load]")
    W, H = 200, 150
    fb = Framebuffer(W, H)
    model = Matrix4.rotation_y(np.radians(30.0))
    view = Matrix4.look_at(np.array([0.0, 0.0, 3.0], dtype=np.float32), np.array([0.0, 0.0, 0.0], dtype=np.float32), np.array([0.0, 1.0, 0.0], dtype=np.float32))
    proj = Matrix4.perspective(np.radians(50.0), W / H, 0.1, 10.0)
    shader = BlinnPhongShader(model, view, proj)
    rasterizer = SoftwareRasterizer(fb, num_threads=gov_status["recommended_safe_workers"])

    graphics_stages = [
        {"stage": 1, "rings": 4,  "sectors": 4,  "description": "Low Poly"},
        {"stage": 2, "rings": 8,  "sectors": 8,  "description": "Standard"},
        {"stage": 3, "rings": 14, "sectors": 14, "description": "High Poly"},
        {"stage": 4, "rings": 20, "sectors": 20, "description": "Extreme"},
    ]

    graphics_results = []
    print(f"{'Stage':<6} {'Triangles':<14} {'Frame Time':<14} {'Graphics FPS':<16} {'Triangles/sec'}")
    print("-" * 75)

    for gs in graphics_stages:
        verts, inds = generate_stress_mesh(gs["rings"], gs["sectors"])
        num_tris = len(inds)

        # Warm-up
        fb.clear()
        rasterizer.draw_mesh(verts, inds, shader)

        # Measurement
        times = []
        for _ in range(2):
            fb.clear()
            t0 = time.perf_counter()
            rasterizer.draw_mesh(verts, inds, shader)
            times.append(time.perf_counter() - t0)

        avg_ft = np.mean(times)
        fps = 1.0 / avg_ft if avg_ft > 0 else 0.0
        tris_sec = num_tris / avg_ft

        graphics_results.append({
            "stage": gs["stage"],
            "triangles": num_tris,
            "description": gs["description"],
            "frame_time_ms": avg_ft * 1000.0,
            "fps": fps,
            "triangles_per_sec": tris_sec
        })

        stage_desc = f"{num_tris:,} ({gs['description']})"
        print(f"{gs['stage']:<6} {stage_desc:<14} {avg_ft * 1000.0:>8.2f} ms     {fps:>10.2f} FPS     {tris_sec:>10,.0f} tri/s")

    # Graphics FPS Degradation Curve
    print("\n[Graphics FPS Degradation Curve (Abfallkurve)]:")
    max_gfx_fps = max(r["fps"] for r in graphics_results)
    for r in graphics_results:
        bar_len = int((r["fps"] / max_gfx_fps) * 35) if max_gfx_fps > 0 else 0
        bar = "█" * bar_len + "░" * (35 - bar_len)
        print(f" Stage {r['stage']} ({r['triangles']:>4} tris): [{bar}] {r['fps']:>5.2f} FPS ({r['frame_time_ms']:>6.1f} ms)")

    # =============================================================
    # Overall Aggregate Score & Saturation Analysis
    # =============================================================
    peak_gflops = max(r["gflops"] for r in compute_results)
    peak_compute_fps = max(r["fps"] for r in compute_results)
    peak_tris_sec = max(r["triangles_per_sec"] for r in graphics_results)

    final_score = int((peak_gflops * 100.0) + (peak_compute_fps * 0.1) + (peak_tris_sec * 0.5))

    print("\n" + "=" * 75)
    print(f" FINAL BENCHMARK SUMMARY & SCORE: {final_score:,} Points")
    print(f" Peak Compute Throughput:         {peak_gflops:.2f} GFLOPS")
    print(f" Peak Compute Rate:               {peak_compute_fps:,.0f} Tasks/sec (FPS)")
    print(f" Peak Geometry Throughput:        {peak_tris_sec:,.0f} Triangles/sec")
    print("=" * 75)

    report = {
        "timestamp": time.time(),
        "hardware": gov_status,
        "final_score": final_score,
        "peak_gflops": peak_gflops,
        "compute_stages": compute_results,
        "graphics_stages": graphics_results
    }
    with open("/workspace/benchmark_load_curve_report.json", "w") as f:
        json.dump(report, f, indent=2)

    return report


if __name__ == "__main__":
    run_load_stress_benchmark()
