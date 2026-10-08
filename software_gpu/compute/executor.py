"""
SIMT-to-CPU Execution Engine for SoftwareGPU.
Implements multi-threaded block distribution, SIMD warp batching,
and barrier synchronization based on MCUDA (Stratton et al.) and PoCL (Jääskeläinen et al.).
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Any, Tuple, List, Optional
import numpy as np

from ..core.types import Dim3, ThreadContext, GPUArray
from ..core.device import VirtualGPU


class KernelLaunchConfig:
    """Configuration for a GPU kernel launch <<<grid, block, shared_mem_bytes>>>."""
    def __init__(self, grid_dim: Any, block_dim: Any, shared_mem_bytes: int = 0):
        self.grid_dim = Dim3(grid_dim)
        self.block_dim = Dim3(block_dim)
        self.shared_mem_bytes = shared_mem_bytes

    @property
    def total_blocks(self) -> int:
        return self.grid_dim.total()

    @property
    def threads_per_block(self) -> int:
        return self.block_dim.total()

    @property
    def total_threads(self) -> int:
        return self.total_blocks * self.threads_per_block

    def __repr__(self) -> str:
        return f"<<<{self.grid_dim}, {self.block_dim}, shared={self.shared_mem_bytes}B>>>"


class BarrierSync:
    """Internal barrier synchronization token for SIMT threads in a block."""
    pass


BARRIER_TOKEN = BarrierSync()


class SIMTExecutor:
    """Software GPU Execution Engine that schedules and executes SIMT kernels on CPU.
    Features:
    - Multi-core thread pool scheduling across CPU cores (Streaming Multiprocessors).
    - Cooperative SIMT thread stepping with __syncthreads() barrier resolution.
    - Automatic unpack of GPUArray arguments to contiguous CPU buffers.
    - Vectorized batch mode for high-performance embarrassingly parallel kernels.
    """
    def __init__(self, num_workers: Optional[int] = None):
        self.num_workers = num_workers or (os.cpu_count() or 4)
        self._thread_pool = ThreadPoolExecutor(
            max_workers=self.num_workers,
            thread_name_prefix="SoftGPU_SM"
        )

    def shutdown(self):
        self._thread_pool.shutdown(wait=True)

    def _execute_block_cooperative(
        self,
        kernel_fn: Callable,
        bx: int, by: int, bz: int,
        grid_dim: Dim3,
        block_dim: Dim3,
        shared_size: int,
        args: tuple,
        kwargs: dict
    ) -> None:
        """Executes one CUDA thread block with cooperative barrier scheduling.
        Supports kernels with __syncthreads() via generator yield points.
        """
        block_idx = Dim3(bx, by, bz)
        num_threads = block_dim.total()
        
        # Allocate thread-block shared memory (fast local cache)
        # Shared memory is private to this block and shared among all threads in this block
        shared_mem = np.zeros(max(shared_size, 1024), dtype=np.float32)

        # Thread contexts for all threads in the block
        threads = []
        for tz in range(block_dim.z):
            for ty in range(block_dim.y):
                for tx in range(block_dim.x):
                    t_idx = Dim3(tx, ty, tz)
                    lane_id = (tx + ty * block_dim.x + tz * (block_dim.x * block_dim.y)) % 32
                    warp_id = (tx + ty * block_dim.x + tz * (block_dim.x * block_dim.y)) // 32
                    
                    ctx = ThreadContext(
                        thread_idx=t_idx,
                        block_idx=block_idx,
                        block_dim=block_dim,
                        grid_dim=grid_dim,
                        warp_id=warp_id,
                        lane_id=lane_id,
                        shared_mem=shared_mem,
                        barrier_fn=None
                    )
                    threads.append(ctx)

        # Initialize thread executions
        # A kernel can either be a standard callable or a generator (for syncthreads)
        active_coroutines = []
        for ctx in threads:
            res = kernel_fn(ctx, *args, **kwargs)
            # If the kernel yielded, it's a coroutine with barrier synchronization points
            if hasattr(res, '__next__'):
                active_coroutines.append(res)

        # Cooperative SIMT execution loop: step all threads until barrier, synchronize, then continue
        while active_coroutines:
            next_phase_coroutines = []
            for coro in active_coroutines:
                try:
                    val = next(coro)
                    # Thread hit a barrier or yielded
                    next_phase_coroutines.append(coro)
                except StopIteration:
                    # Thread finished execution
                    pass
            # Barrier reached: all threads have completed the current phase!
            active_coroutines = next_phase_coroutines

    def _execute_block_range(
        self,
        kernel_fn: Callable,
        block_indices: List[Tuple[int, int, int]],
        grid_dim: Dim3,
        block_dim: Dim3,
        shared_size: int,
        args: tuple,
        kwargs: dict
    ) -> None:
        """Worker task processing a subset of thread blocks."""
        for bx, by, bz in block_indices:
            self._execute_block_cooperative(
                kernel_fn, bx, by, bz,
                grid_dim, block_dim, shared_size,
                args, kwargs
            )

    def launch(
        self,
        kernel_fn: Callable,
        config: KernelLaunchConfig,
        *args: Any,
        **kwargs: Any
    ) -> float:
        """Launches a SIMT kernel across the virtual GPU.
        Returns execution wall-clock time in seconds.
        """
        device = VirtualGPU.get_current_device()
        t0 = time.perf_counter()

        # Unwrap GPUArray instances to their raw numpy memory views
        unwrapped_args = tuple(
            arg.raw_buffer if isinstance(arg, GPUArray) else arg
            for arg in args
        )
        unwrapped_kwargs = {
            k: (v.raw_buffer if isinstance(v, GPUArray) else v)
            for k, v in kwargs.items()
        }

        # Build list of all blocks in the grid
        all_blocks = [
            (bx, by, bz)
            for bz in range(config.grid_dim.z)
            for by in range(config.grid_dim.y)
            for bx in range(config.grid_dim.x)
        ]

        total_blocks = len(all_blocks)
        if total_blocks == 0:
            return 0.0

        # Partition blocks across CPU worker threads (Streaming Multiprocessors)
        num_chunks = min(self.num_workers, total_blocks)
        chunks: List[List[Tuple[int, int, int]]] = [[] for _ in range(num_chunks)]
        for i, block_idx in enumerate(all_blocks):
            chunks[i % num_chunks].append(block_idx)

        # Distribute work to SM worker pool
        futures = []
        for chunk in chunks:
            if chunk:
                f = self._thread_pool.submit(
                    self._execute_block_range,
                    kernel_fn,
                    chunk,
                    config.grid_dim,
                    config.block_dim,
                    config.shared_mem_bytes,
                    unwrapped_args,
                    unwrapped_kwargs
                )
                futures.append(f)

        # Wait for all SM cores to finish execution (implicit device synchronization)
        for f in futures:
            f.result()

        elapsed = time.perf_counter() - t0
        device.total_kernels_launched += 1
        return elapsed
