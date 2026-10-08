"""
Standard GPU Compute Kernels implemented for SoftwareGPU.
Features Tiled Matrix Multiplication with Shared Memory and Barriers,
2D Convolution, Parallel Reduction, and SIMD-vectorized Operations.
"""

import math
import numpy as np
from typing import Tuple, Optional
from .compiler import cuda_kernel
from .executor import SIMTExecutor, KernelLaunchConfig
from ..core.types import GPUArray, Dim3
from ..core.device import VirtualGPU


# =====================================================================
# 1. Tiled Matrix Multiplication (SIMT with Shared Memory and Barriers)
# =====================================================================

def matmul_tiled_simt_kernel(ctx, A, B, C, N: int, TILE_SIZE: int):
    """Classic CUDA Tiled Matrix Multiplication using cooperative shared memory tiles.
    Uses generator yield points for CUDA __syncthreads() synchronization.
    """
    row = ctx.blockIdx.y * ctx.blockDim.y + ctx.threadIdx.y
    col = ctx.blockIdx.x * ctx.blockDim.x + ctx.threadIdx.x
    
    ty = ctx.threadIdx.y
    tx = ctx.threadIdx.x
    
    # Shared memory layout: two tiles of size TILE_SIZE x TILE_SIZE
    tile_elements = TILE_SIZE * TILE_SIZE
    shared = ctx.shared  # 1D buffer of floats

    acc = 0.0
    num_tiles = (N + TILE_SIZE - 1) // TILE_SIZE

    for m in range(num_tiles):
        # Phase 1: Load tile into shared memory
        k_a = m * TILE_SIZE + tx
        k_b = m * TILE_SIZE + ty
        
        # Load A[row, k_a] into shared tile A
        if row < N and k_a < N:
            shared[ty * TILE_SIZE + tx] = A[row, k_a]
        else:
            shared[ty * TILE_SIZE + tx] = 0.0

        # Load B[k_b, col] into shared tile B
        if k_b < N and col < N:
            shared[tile_elements + ty * TILE_SIZE + tx] = B[k_b, col]
        else:
            shared[tile_elements + ty * TILE_SIZE + tx] = 0.0

        # Synchronize all threads in the block so tiles are fully populated
        yield  # Equivalent to ctx.syncthreads()

        # Phase 2: Compute partial dot product from shared memory tiles
        for k in range(TILE_SIZE):
            acc += shared[ty * TILE_SIZE + k] * shared[tile_elements + k * TILE_SIZE + tx]

        # Synchronize before overwriting shared memory in the next iteration
        yield  # Equivalent to ctx.syncthreads()

    if row < N and col < N:
        C[row, col] = acc


# =====================================================================
# 2. Parallel Reduction (Tree reduction with Shared Memory & Barriers)
# =====================================================================

def parallel_reduction_sum_kernel(ctx, d_in, d_out, n: int):
    """CUDA tree reduction kernel with intra-block synchronization."""
    tid = ctx.threadIdx.x
    i = ctx.blockIdx.x * (ctx.blockDim.x * 2) + ctx.threadIdx.x
    shared = ctx.shared

    # Load first element and first reduction step from global memory
    my_sum = 0.0
    if i < n:
        my_sum += d_in[i]
    if i + ctx.blockDim.x < n:
        my_sum += d_in[i + ctx.blockDim.x]

    shared[tid] = my_sum
    yield  # __syncthreads()

    # In-block tree reduction
    stride = ctx.blockDim.x // 2
    while stride > 0:
        if tid < stride:
            shared[tid] += shared[tid + stride]
        yield  # __syncthreads()
        stride //= 2

    # Thread 0 writes block result to global memory
    if tid == 0:
        d_out[ctx.blockIdx.x] = shared[0]


# =====================================================================
# 3. 2D Convolution / Stencil Kernel
# =====================================================================

def conv2d_simt_kernel(ctx, image, kernel, output, width: int, height: int, ksize: int):
    """2D spatial convolution kernel executed across a 2D thread grid."""
    x = ctx.blockIdx.x * ctx.blockDim.x + ctx.threadIdx.x
    y = ctx.blockIdx.y * ctx.blockDim.y + ctx.threadIdx.y
    radius = ksize // 2

    if x < width and y < height:
        acc = 0.0
        for ky in range(-radius, radius + 1):
            iy = min(max(y + ky, 0), height - 1)
            for kx in range(-radius, radius + 1):
                ix = min(max(x + kx, 0), width - 1)
                weight = kernel[ky + radius, kx + radius]
                acc += image[iy, ix] * weight
        output[y, x] = acc


# =====================================================================
# 4. SIMD / Work-Group Vectorized Accelerators (PoCL style)
# =====================================================================

class VectorizedGPUKernels:
    """High-throughput vectorized execution kernels for CPU SIMD hardware.
    Maps whole thread-blocks to AVX2/FMA vector instructions on CPU cores.
    """
    @staticmethod
    def vector_add(d_a: GPUArray, d_b: GPUArray, d_c: GPUArray) -> None:
        np.add(d_a.raw_buffer, d_b.raw_buffer, out=d_c.raw_buffer)
        VirtualGPU.get_current_device().total_flops += d_a.size

    @staticmethod
    def vector_mul(d_a: GPUArray, d_b: GPUArray, d_c: GPUArray) -> None:
        np.multiply(d_a.raw_buffer, d_b.raw_buffer, out=d_c.raw_buffer)
        VirtualGPU.get_current_device().total_flops += d_a.size

    @staticmethod
    def vector_fma(d_a: GPUArray, d_b: GPUArray, d_c: GPUArray, d_out: GPUArray) -> None:
        # Fused Multiply-Add: d_out = d_a * d_b + d_c
        np.multiply(d_a.raw_buffer, d_b.raw_buffer, out=d_out.raw_buffer)
        np.add(d_out.raw_buffer, d_c.raw_buffer, out=d_out.raw_buffer)
        VirtualGPU.get_current_device().total_flops += d_a.size * 2

    @staticmethod
    def relu(d_in: GPUArray, d_out: GPUArray) -> None:
        np.maximum(d_in.raw_buffer, 0.0, out=d_out.raw_buffer)
        VirtualGPU.get_current_device().total_flops += d_in.size

    @staticmethod
    def gelu(d_in: GPUArray, d_out: GPUArray) -> None:
        # 0.5 * x * (1 + tanh(sqrt(2/pi) * (x + 0.044715 * x^3)))
        x = d_in.raw_buffer
        sqrt_2_pi = math.sqrt(2.0 / math.pi)
        inner = sqrt_2_pi * (x + 0.044715 * (x ** 3))
        d_out.raw_buffer[...] = 0.5 * x * (1.0 + np.tanh(inner))
        VirtualGPU.get_current_device().total_flops += d_in.size * 8

    @staticmethod
    def gemm_parallel(d_a: GPUArray, d_b: GPUArray, d_c: GPUArray) -> None:
        """High performance tiled/vectorized GEMM on CPU vector units (OpenBLAS/AVX2)."""
        np.matmul(d_a.raw_buffer, d_b.raw_buffer, out=d_c.raw_buffer)
        m, k = d_a.shape
        _, n = d_b.shape
        VirtualGPU.get_current_device().total_flops += 2 * m * n * k
