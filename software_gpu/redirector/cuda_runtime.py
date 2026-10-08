"""
Drop-in CUDA Runtime API replacement for SoftwareGPU.
Allows CUDA-targeted code to run directly on the CPU via SoftwareGPU redirection.
"""

from typing import Tuple, Optional, Any
import numpy as np

from ..core.device import VirtualGPU
from ..core.types import GPUArray, Dim3
from ..compute.compiler import cuda_kernel


class CUDARuntime:
    """Emulates NVIDIA CUDA Runtime API (numba.cuda / cuda-python style)."""
    @staticmethod
    def is_available() -> bool:
        """Returns True because the software GPU processor fulfills all GPU workloads."""
        return True

    @staticmethod
    def device_count() -> int:
        return 1

    @staticmethod
    def get_device_name(device_id: int = 0) -> str:
        dev = VirtualGPU.get_current_device()
        return f"{dev.properties.name} [Redirected to {dev.num_sms} CPU Cores]"

    @staticmethod
    def to_device(host_array: np.ndarray) -> GPUArray:
        """Copies host NumPy array into virtual GPU memory."""
        dev = VirtualGPU.get_current_device()
        return dev.memory.to_device(host_array)

    @staticmethod
    def device_array(shape: Tuple[int, ...], dtype: np.dtype = np.float32) -> GPUArray:
        """Allocates uninitialized memory on virtual GPU."""
        dev = VirtualGPU.get_current_device()
        return dev.memory.allocate(shape, dtype)

    @staticmethod
    def synchronize() -> None:
        """Synchronizes host and device execution."""
        VirtualGPU.get_current_device().synchronize()

    @staticmethod
    def jit(func=None, **kwargs):
        """Decorator equivalent to @cuda.jit."""
        return cuda_kernel(func)


# Global cuda singleton instance
cuda = CUDARuntime()
