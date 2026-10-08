"""
Kernel Decorator and Launch Syntax Handler for SoftwareGPU.
Provides CUDA-style syntax: `my_kernel[grid_dim, block_dim](args...)`.
"""

import functools
from typing import Callable, Any, Optional
from .executor import SIMTExecutor, KernelLaunchConfig
from ..core.types import Dim3


class CompiledKernel:
    """Wrapper around a Python function designated as a GPU kernel.
    Provides indexing syntax `kernel[grid, block](*args)` matching CUDA Python / Numba.
    """
    def __init__(self, fn: Callable, executor: Optional[SIMTExecutor] = None):
        self.fn = fn
        self.executor = executor or SIMTExecutor()
        functools.update_wrapper(self, fn)

    def __getitem__(self, config_args: Any) -> Callable:
        """Handles indexing syntax: kernel[grid, block] or kernel[grid, block, shared_bytes]."""
        if isinstance(config_args, tuple):
            if len(config_args) == 2:
                grid, block = config_args
                shared_bytes = 0
            elif len(config_args) == 3:
                grid, block, shared_bytes = config_args
            else:
                raise ValueError("Expected [grid_dim, block_dim] or [grid_dim, block_dim, shared_bytes]")
        else:
            raise ValueError("Kernel indexing requires at least grid and block dimensions.")

        launch_config = KernelLaunchConfig(grid, block, shared_bytes)

        def launcher(*args: Any, **kwargs: Any) -> float:
            return self.executor.launch(self.fn, launch_config, *args, **kwargs)

        return launcher

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Direct call fallback if invoked without indexing."""
        raise RuntimeError("GPU kernels must be launched with grid and block dimensions: kernel[grid, block](*args)")


def cuda_kernel(fn: Callable = None, executor: Optional[SIMTExecutor] = None) -> Any:
    """Decorator to mark a function as an executable GPU SIMT kernel.
    
    Usage:
        @cuda_kernel
        def vector_add(ctx, a, b, c):
            idx = ctx.blockIdx.x * ctx.blockDim.x + ctx.threadIdx.x
            if idx < len(c):
                c[idx] = a[idx] + b[idx]

        vector_add[grid_size, block_size](d_a, d_b, d_c)
    """
    if fn is None:
        return lambda f: CompiledKernel(f, executor)
    return CompiledKernel(fn, executor)


gpu_kernel = cuda_kernel
