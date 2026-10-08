"""
Demonstration: Redirecting CUDA Workloads to CPU using SoftwareGPU.
Illustrates how code intended for dedicated GPUs runs seamlessly on CPU.
"""

import numpy as np
from software_gpu.redirector.cuda_runtime import cuda
from software_gpu.core.device import VirtualGPU


# Define a CUDA SIMT kernel using @cuda.jit
@cuda.jit
def vector_multiply_and_bias(ctx, a, b, bias, c, n):
    idx = ctx.blockIdx.x * ctx.blockDim.x + ctx.threadIdx.x
    if idx < n:
        c[idx] = a[idx] * b[idx] + bias


def main():
    print("=== SoftwareGPU CUDA-to-CPU Redirection Demo ===")
    print(f"CUDA Available: {cuda.is_available()}")
    print(f"Device Name: {cuda.get_device_name(0)}")

    N = 100_000
    print(f"\nAllocating and preparing {N:,} elements on host...")
    host_a = np.linspace(1.0, 10.0, N, dtype=np.float32)
    host_b = np.linspace(2.0, 5.0, N, dtype=np.float32)
    bias_val = 42.0

    # Transfer to Virtual GPU Memory (simulated on CPU host memory subsystem)
    print("Transferring data to Virtual GPU VRAM via cuda.to_device()...")
    d_a = cuda.to_device(host_a)
    d_b = cuda.to_device(host_b)
    d_c = cuda.device_array((N,), dtype=np.float32)

    # Calculate grid & block dimensions
    threads_per_block = 256
    blocks_per_grid = (N + threads_per_block - 1) // threads_per_block
    print(f"Kernel configuration: Grid={blocks_per_grid} blocks, Block={threads_per_block} threads/block")

    # Launch kernel using standard CUDA syntax: kernel[grid, block](args...)
    print("Launching CUDA kernel redirected to CPU Streaming Multiprocessors...")
    elapsed = vector_multiply_and_bias[blocks_per_grid, threads_per_block](
        d_a, d_b, bias_val, d_c, N
    )
    cuda.synchronize()
    print(f"Kernel executed successfully in {elapsed * 1000.0:.2f} ms")

    # Copy results back to host
    print("Copying results back to host via copy_to_host()...")
    host_c = d_c.copy_to_host()

    # Verify numerical correctness against CPU ground truth
    expected = (host_a * host_b) + bias_val
    max_error = np.max(np.abs(host_c - expected))
    print(f"Verification: Max absolute error = {max_error:.2e}")
    assert max_error < 1e-4, "Numerical error exceeded threshold!"
    print("SUCCESS: Result matches mathematical ground truth exactly without physical GPU hardware!")


if __name__ == "__main__":
    main()
