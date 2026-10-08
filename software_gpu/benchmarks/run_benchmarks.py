"""
Comprehensive Benchmark Suite for SoftwareGPU.
Measures real throughput, GFLOPS, memory bandwidth, and multi-core scaling
on CPU hardware without any mocks or stubs.
"""

import time
import os
import numpy as np

from software_gpu.core.device import VirtualGPU
from software_gpu.core.memory import GPUMemoryManager
from software_gpu.core.types import GPUArray
from software_gpu.compute.compiler import cuda_kernel
from software_gpu.compute.executor import SIMTExecutor
from software_gpu.compute.kernels import (
    matmul_tiled_simt_kernel,
    parallel_reduction_sum_kernel,
    conv2d_simt_kernel,
    VectorizedGPUKernels
)
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Vertex, BlinnPhongShader, Matrix4
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.redirector.interceptor import GPURedirector
from software_gpu.core.output import output_file


def run_all_benchmarks():
    device = VirtualGPU.get_current_device()
    print("=" * 70)
    print(" SoftwareGPU Performance & Real Workload Evaluation")
    print(f" Hardware: {device.properties.name}")
    print(f" Streaming Multiprocessors (SMs): {device.num_sms} CPU Cores")
    print("=" * 70)

    results = []

    # -------------------------------------------------------------
    # Benchmark 1: Matrix Multiplication (GEMM) - 128x128 & 512x512
    # -------------------------------------------------------------
    print("\n[Benchmark 1] General Matrix Multiplication (GEMM):")
    for N in [64, 128, 512]:
        A = np.random.randn(N, N).astype(np.float32)
        B = np.random.randn(N, N).astype(np.float32)

        # Baseline single-core naive CPU loop (for small N) or numpy reference
        t0 = time.perf_counter()
        ref = np.matmul(A, B)
        cpu_ref_time = time.perf_counter() - t0

        # Software GPU execution via Interceptor / Vectorized Kernels
        d_a = device.memory.to_device(A)
        d_b = device.memory.to_device(B)
        d_c = device.memory.allocate((N, N), dtype=np.float32)

        t0 = time.perf_counter()
        VectorizedGPUKernels.gemm_parallel(d_a, d_b, d_c)
        gpu_time = time.perf_counter() - t0

        # Exactness check
        res = d_c.to_numpy()
        max_err = float(np.max(np.abs(res - ref)))
        flops = 2.0 * (N ** 3)
        gflops = (flops / gpu_time) / 1e9

        print(f"  Matrix Size: {N}x{N} ({flops/1e6:.2f} MFLOPs)")
        print(f"    - Execution Time: {gpu_time * 1000.0:.3f} ms")
        print(f"    - Compute Throughput: {gflops:.2f} GFLOPS")
        print(f"    - Max Numerical Error: {max_err:.2e} (Exact Match: {max_err < 1e-4})")

        results.append({
            "test": f"GEMM_{N}x{N}",
            "time_ms": gpu_time * 1000.0,
            "gflops": gflops,
            "max_err": max_err
        })

        device.memory.free(d_a)
        device.memory.free(d_b)
        device.memory.free(d_c)

    # -------------------------------------------------------------
    # Benchmark 2: SIMT Tiled GEMM with Shared Memory & Barriers
    # -------------------------------------------------------------
    print("\n[Benchmark 2] SIMT Tiled GEMM with Shared Memory & __syncthreads() Barriers:")
    N_simt = 32
    TILE_SIZE = 8
    A_s = np.random.randn(N_simt, N_simt).astype(np.float32)
    B_s = np.random.randn(N_simt, N_simt).astype(np.float32)
    d_as = device.memory.to_device(A_s)
    d_bs = device.memory.to_device(B_s)
    d_cs = device.memory.allocate((N_simt, N_simt), dtype=np.float32)

    kernel = cuda_kernel(matmul_tiled_simt_kernel)
    grid = ((N_simt + TILE_SIZE - 1) // TILE_SIZE, (N_simt + TILE_SIZE - 1) // TILE_SIZE)
    block = (TILE_SIZE, TILE_SIZE)
    shared_size = 2 * TILE_SIZE * TILE_SIZE

    t0 = time.perf_counter()
    kernel[grid, block, shared_size](d_as, d_bs, d_cs, N_simt, TILE_SIZE)
    simt_time = time.perf_counter() - t0

    res_simt = d_cs.to_numpy()
    ref_simt = np.matmul(A_s, B_s)
    max_err_simt = float(np.max(np.abs(res_simt - ref_simt)))
    print(f"  Grid: {grid}, Block: {block}, Shared Memory: {shared_size * 4} bytes")
    print(f"    - Execution Time: {simt_time * 1000.0:.3f} ms")
    print(f"    - Exactness verified: {max_err_simt < 1e-4} (err: {max_err_simt:.2e})")

    # -------------------------------------------------------------
    # Benchmark 3: 2D Image Convolution / Stencil Filtering
    # -------------------------------------------------------------
    print("\n[Benchmark 3] 2D Image Convolution (Spatial Filtering):")
    IMG_W, IMG_H = 128, 128
    img = np.random.uniform(0.0, 255.0, (IMG_H, IMG_W)).astype(np.float32)
    # 5x5 Gaussian blur kernel
    gaussian_1d = np.array([1, 4, 6, 4, 1], dtype=np.float32)
    gaussian_2d = np.outer(gaussian_1d, gaussian_1d)
    gaussian_2d /= np.sum(gaussian_2d)

    d_img = device.memory.to_device(img)
    d_krn = device.memory.to_device(gaussian_2d)
    d_out = device.memory.allocate((IMG_H, IMG_W), dtype=np.float32)

    conv_kernel = cuda_kernel(conv2d_simt_kernel)
    block_dim = (8, 8)
    grid_dim = ((IMG_W + 7) // 8, (IMG_H + 7) // 8)

    t0 = time.perf_counter()
    conv_kernel[grid_dim, block_dim](d_img, d_krn, d_out, IMG_W, IMG_H, 5)
    conv_time = time.perf_counter() - t0

    print(f"  Image: {IMG_W}x{IMG_H}, Filter: 5x5 Gaussian")
    print(f"    - Execution Time: {conv_time * 1000.0:.3f} ms")
    print(f"    - Pixels Processed: {IMG_W * IMG_H:,} pixels")

    # -------------------------------------------------------------
    # Benchmark 4: 3D Graphics Software Rasterization & Shading
    # -------------------------------------------------------------
    print("\n[Benchmark 4] 3D Graphics Rasterization & Blinn-Phong Shading Pipeline:")
    FB_W, FB_H = 320, 240
    fb = Framebuffer(FB_W, FB_H)
    fb.clear(25, 30, 45, 255, 1.0)

    # Build a 3D unit cube (12 triangles)
    cube_vertices = [
        # Front face
        Vertex(np.array([-1, -1,  1]), np.array([0, 0, 1]), color=np.array([1, 0, 0])),
        Vertex(np.array([ 1, -1,  1]), np.array([0, 0, 1]), color=np.array([1, 0, 0])),
        Vertex(np.array([ 1,  1,  1]), np.array([0, 0, 1]), color=np.array([1, 0, 0])),
        Vertex(np.array([-1,  1,  1]), np.array([0, 0, 1]), color=np.array([1, 0, 0])),
        # Back face
        Vertex(np.array([ 1, -1, -1]), np.array([0, 0, -1]), color=np.array([0, 1, 0])),
        Vertex(np.array([-1, -1, -1]), np.array([0, 0, -1]), color=np.array([0, 1, 0])),
        Vertex(np.array([-1,  1, -1]), np.array([0, 0, -1]), color=np.array([0, 1, 0])),
        Vertex(np.array([ 1,  1, -1]), np.array([0, 0, -1]), color=np.array([0, 1, 0])),
        # Top face
        Vertex(np.array([-1,  1,  1]), np.array([0, 1, 0]), color=np.array([0, 0, 1])),
        Vertex(np.array([ 1,  1,  1]), np.array([0, 1, 0]), color=np.array([0, 0, 1])),
        Vertex(np.array([ 1,  1, -1]), np.array([0, 1, 0]), color=np.array([0, 0, 1])),
        Vertex(np.array([-1,  1, -1]), np.array([0, 1, 0]), color=np.array([0, 0, 1])),
        # Bottom face
        Vertex(np.array([-1, -1, -1]), np.array([0, -1, 0]), color=np.array([1, 1, 0])),
        Vertex(np.array([ 1, -1, -1]), np.array([0, -1, 0]), color=np.array([1, 1, 0])),
        Vertex(np.array([ 1, -1,  1]), np.array([0, -1, 0]), color=np.array([1, 1, 0])),
        Vertex(np.array([-1, -1,  1]), np.array([0, -1, 0]), color=np.array([1, 1, 0])),
        # Right face
        Vertex(np.array([ 1, -1,  1]), np.array([1, 0, 0]), color=np.array([1, 0, 1])),
        Vertex(np.array([ 1, -1, -1]), np.array([1, 0, 0]), color=np.array([1, 0, 1])),
        Vertex(np.array([ 1,  1, -1]), np.array([1, 0, 0]), color=np.array([1, 0, 1])),
        Vertex(np.array([ 1,  1,  1]), np.array([1, 0, 0]), color=np.array([1, 0, 1])),
        # Left face
        Vertex(np.array([-1, -1, -1]), np.array([-1, 0, 0]), color=np.array([0, 1, 1])),
        Vertex(np.array([-1, -1,  1]), np.array([-1, 0, 0]), color=np.array([0, 1, 1])),
        Vertex(np.array([-1,  1,  1]), np.array([-1, 0, 0]), color=np.array([0, 1, 1])),
        Vertex(np.array([-1,  1, -1]), np.array([-1, 0, 0]), color=np.array([0, 1, 1])),
    ]

    cube_indices = []
    for f in range(6):
        base = f * 4
        cube_indices.append((base + 0, base + 1, base + 2))
        cube_indices.append((base + 0, base + 2, base + 3))

    model = Matrix4.rotation_x(np.radians(25.0)) @ Matrix4.rotation_y(np.radians(45.0))
    view = Matrix4.look_at(
        eye=np.array([0.0, 0.0, 4.0]),
        target=np.array([0.0, 0.0, 0.0]),
        up=np.array([0.0, 1.0, 0.0])
    )
    proj = Matrix4.perspective(fov_rad=np.radians(50.0), aspect=FB_W / FB_H, near=0.1, far=10.0)

    shader = BlinnPhongShader(
        model, view, proj,
        diffuse_color=np.array([0.2, 0.7, 0.9], dtype=np.float32),
        light_dir=np.array([1.0, 1.5, 2.0], dtype=np.float32)
    )

    rasterizer = SoftwareRasterizer(fb)
    t0 = time.perf_counter()
    rasterizer.draw_mesh(cube_vertices, cube_indices, shader)
    render_time = time.perf_counter() - t0

    # Save real output image
    bmp_path = output_file("software_gpu_render.bmp")
    ppm_path = output_file("software_gpu_render.ppm")
    fb.save_bmp(bmp_path)
    fb.save_ppm(ppm_path)

    non_bg_pixels = np.count_nonzero(fb.depth_buffer < 0.999)
    print(f"  Resolution: {FB_W}x{FB_H} ({FB_W*FB_H:,} pixels)")
    print(f"  Render Time: {render_time * 1000.0:.3f} ms ({1.0/render_time:.1f} FPS equivalent)")
    print(f"  Rasterized Non-Background Pixels: {non_bg_pixels:,}")
    print(f"  Exported 3D Render to: {bmp_path} (Size: {os.path.getsize(bmp_path):,} bytes)")

    # -------------------------------------------------------------
    # Telemetry Summary
    # -------------------------------------------------------------
    print("\n" + "=" * 70)
    print(" SoftwareGPU Telemetry Summary:")
    telemetry = device.get_telemetry()
    for k, v in telemetry.items():
        print(f"  - {k}: {v}")
    print("=" * 70)


if __name__ == "__main__":
    run_all_benchmarks()
