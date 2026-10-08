"""
GPU Task Interceptor & Redirection Engine.
Intercepts hardware GPU offload requests and transparently routes them to CPU SoftwareGPU.
Tracks hardware redirection metrics and performance telemetry.
"""

import time
from typing import Dict, Any, Callable, Optional, Tuple
import numpy as np

from ..core.device import VirtualGPU
from ..core.types import GPUArray
from ..compute.kernels import VectorizedGPUKernels
from ..compute.executor import SIMTExecutor, KernelLaunchConfig


class GPURedirector:
    """Intercepts tasks targeted at GPU hardware and routes them to CPU execution."""
    def __init__(self):
        self.device = VirtualGPU.get_current_device()
        self.executor = SIMTExecutor()
        self.intercepted_tasks = 0
        self.total_redirected_time = 0.0

    def dispatch(
        self,
        task_name: str,
        func: Callable,
        target_device: str = "gpu",
        *args, **kwargs
    ) -> Any:
        """Intercepts a function call targeted at a GPU, logs redirection, and executes on CPU."""
        if target_device.lower() in ("gpu", "cuda", "opencl", "vulkan"):
            # Workload redirection to Software GPU
            t0 = time.perf_counter()
            self.intercepted_tasks += 1
            result = func(*args, **kwargs)
            duration = time.perf_counter() - t0
            self.total_redirected_time += duration
            return result
        else:
            # Native CPU path
            return func(*args, **kwargs)

    def execute_gemm(
        self,
        A: np.ndarray,
        B: np.ndarray,
        target_device: str = "cuda"
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Intercepts GPU matrix multiplication and executes on CPU vector units."""
        t0 = time.perf_counter()
        d_a = self.device.memory.to_device(A)
        d_b = self.device.memory.to_device(B)
        d_c = self.device.memory.allocate((A.shape[0], B.shape[1]), dtype=A.dtype)

        # Execute on Software GPU
        VectorizedGPUKernels.gemm_parallel(d_a, d_b, d_c)

        # Retrieve result
        result = d_c.to_numpy()
        self.device.memory.free(d_a)
        self.device.memory.free(d_b)
        self.device.memory.free(d_c)

        elapsed = time.perf_counter() - t0
        flops = 2 * A.shape[0] * A.shape[1] * B.shape[1]
        gflops = (flops / elapsed) / 1e9

        stats = {
            "task": "GEMM",
            "redirected_from": target_device,
            "redirected_to": f"SoftwareGPU ({self.device.num_sms} SMs on CPU)",
            "matrix_shape": f"{A.shape} x {B.shape}",
            "elapsed_ms": elapsed * 1000.0,
            "gflops": gflops
        }
        return result, stats

    def execute_activation(
        self,
        X: np.ndarray,
        activation_type: str = "relu",
        target_device: str = "cuda"
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Intercepts GPU tensor activation pass and executes on CPU vector units."""
        t0 = time.perf_counter()
        d_in = self.device.memory.to_device(X)
        d_out = self.device.memory.allocate(X.shape, dtype=X.dtype)

        if activation_type.lower() == "relu":
            VectorizedGPUKernels.relu(d_in, d_out)
        elif activation_type.lower() == "gelu":
            VectorizedGPUKernels.gelu(d_in, d_out)
        else:
            raise ValueError(f"Unknown activation type: {activation_type}")

        result = d_out.to_numpy()
        self.device.memory.free(d_in)
        self.device.memory.free(d_out)

        elapsed = time.perf_counter() - t0
        stats = {
            "task": f"Activation_{activation_type.upper()}",
            "redirected_from": target_device,
            "redirected_to": f"SoftwareGPU ({self.device.num_sms} SMs on CPU)",
            "elements": X.size,
            "elapsed_ms": elapsed * 1000.0,
        }
        return result, stats


redirector = GPURedirector()
