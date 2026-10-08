"""
GPU Memory Management Subsystem for SoftwareGPU.
Emulates VRAM addressing, Host-to-Device transfers, Shared Memory Banking,
and Unified Memory architecture based on GPU hardware principles.
"""

from typing import Dict, Optional, Tuple, Any
import numpy as np
from .types import GPUArray


class MemoryCopyKind:
    HOST_TO_DEVICE = 1
    DEVICE_TO_HOST = 2
    DEVICE_TO_DEVICE = 3


class GPUMemoryManager:
    """Manages virtual VRAM allocation, memory mappings, and transfer bus.
    Simulates high-bandwidth memory (HBM/GDDR6) subsystem on host memory.
    """
    def __init__(self, total_vram_bytes: int = 4 * 1024 * 1024 * 1024):  # Default 4GB virtual VRAM
        self.total_vram_bytes = total_vram_bytes
        self.allocated_bytes = 0
        self.peak_allocated_bytes = 0
        self._next_virtual_addr = 0x10000000  # Base virtual address
        self._allocations: Dict[int, GPUArray] = {}
        
        # Telemetry metrics
        self.total_host_to_device_bytes = 0
        self.total_device_to_host_bytes = 0
        self.transfer_count = 0

    def allocate(self, shape: Tuple[int, ...], dtype: np.dtype = np.float32) -> GPUArray:
        """Allocates contiguous GPU device memory buffer (cudaMalloc)."""
        dt = np.dtype(dtype)
        size = int(np.prod(shape))
        nbytes = size * dt.itemsize

        if self.allocated_bytes + nbytes > self.total_vram_bytes:
            raise MemoryError(
                f"Virtual GPU Out of Memory! Requested {nbytes} bytes, "
                f"Available {self.total_vram_bytes - self.allocated_bytes} bytes."
            )

        # Align address to 128-byte boundary (standard GPU coalescing alignment)
        addr = self._next_virtual_addr
        self._next_virtual_addr += ((nbytes + 127) // 128) * 128
        self.allocated_bytes += nbytes
        self.peak_allocated_bytes = max(self.peak_allocated_bytes, self.allocated_bytes)

        gpu_array = GPUArray(
            shape=shape,
            dtype=dt,
            device_ptr=addr,
            memory_manager=self
        )
        self._allocations[addr] = gpu_array
        return gpu_array

    def to_device(self, host_array: np.ndarray) -> GPUArray:
        """Allocates GPU memory and copies host data into it (cudaMemcpyHostToDevice)."""
        host_arr = np.ascontiguousarray(host_array)
        device_arr = self.allocate(host_arr.shape, host_arr.dtype)
        device_arr.copy_from_host(host_arr)
        
        nbytes = host_arr.nbytes
        self.total_host_to_device_bytes += nbytes
        self.transfer_count += 1
        return device_arr

    def free(self, gpu_array: GPUArray) -> None:
        """Frees allocated device memory (cudaFree)."""
        addr = gpu_array.device_ptr
        if addr in self._allocations:
            self.allocated_bytes -= gpu_array.nbytes
            del self._allocations[addr]

    def memcpy(self, dst: Any, src: Any, count: int, kind: int) -> None:
        """Generic memory copy bus emulation."""
        self.transfer_count += 1
        if kind == MemoryCopyKind.HOST_TO_DEVICE:
            assert isinstance(dst, GPUArray) and isinstance(src, np.ndarray)
            dst.copy_from_host(src)
            self.total_host_to_device_bytes += count
        elif kind == MemoryCopyKind.DEVICE_TO_HOST:
            assert isinstance(dst, np.ndarray) and isinstance(src, GPUArray)
            src.copy_to_host(dst)
            self.total_device_to_host_bytes += count
        elif kind == MemoryCopyKind.DEVICE_TO_DEVICE:
            assert isinstance(dst, GPUArray) and isinstance(src, GPUArray)
            dst._data[...] = src._data[...]
        else:
            raise ValueError(f"Unknown memory copy kind: {kind}")

    def reset(self) -> None:
        """Resets the memory manager allocations and stats."""
        self._allocations.clear()
        self.allocated_bytes = 0
        self._next_virtual_addr = 0x10000000


class SharedMemoryBank:
    """Simulates on-chip Shared Memory (__shared__ in CUDA / __local in OpenCL).
    Provides 32 banks for conflict-free parallel access, matching hardware SM cache.
    """
    def __init__(self, size_in_words: int = 16384, num_banks: int = 32):
        self.num_banks = num_banks
        self.size = size_in_words
        self._storage = np.zeros(size_in_words, dtype=np.float32)
        self.bank_conflicts = 0

    def get_storage(self) -> np.ndarray:
        return self._storage

    def reset(self) -> None:
        self._storage.fill(0)
        self.bank_conflicts = 0
