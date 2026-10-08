"""
Virtual GPU Device Abstraction for SoftwareGPU.
Defines hardware topology (SMs, Warp size, caches, memory architecture).
"""

import os
from dataclasses import dataclass
from typing import Dict, Any, Optional
from .memory import GPUMemoryManager


@dataclass
class DeviceProperties:
    name: str = "Virtual-Software-GPU (SIMT-CPU Architecture)"
    major: int = 8  # Compute capability 8.6 equivalent
    minor: int = 6
    total_global_mem: int = 4 * 1024 * 1024 * 1024  # 4 GB
    shared_mem_per_block: int = 49152  # 48 KB
    regs_per_block: int = 65536
    warp_size: int = 32
    max_threads_per_block: int = 1024
    max_threads_dim: tuple = (1024, 1024, 64)
    max_grid_size: tuple = (65535, 65535, 65535)
    multi_processor_count: int = 10  # Matches host CPU cores
    clock_rate_khz: int = 2500000  # 2.5 GHz
    memory_clock_rate_khz: int = 1750000
    memory_bus_width: int = 256  # 256-bit bus
    l2_cache_size: int = 4 * 1024 * 1024  # 4 MB L2 cache


class VirtualGPU:
    """Represents a virtual software GPU processor running on the host CPU.
    Redirects parallel compute workloads and graphics commands to host vector units.
    """
    _instance: Optional['VirtualGPU'] = None

    def __init__(self, num_sm_cores: Optional[int] = None, vram_bytes: int = 4 * 1024 * 1024 * 1024):
        cpu_count = os.cpu_count() or 4
        self.num_sms = num_sm_cores if num_sm_cores is not None else cpu_count
        self.properties = DeviceProperties(
            total_global_mem=vram_bytes,
            multi_processor_count=self.num_sms
        )
        self.memory = GPUMemoryManager(total_vram_bytes=vram_bytes)
        self._is_active = True
        
        # Performance Counters
        self.total_kernels_launched = 0
        self.total_draw_calls = 0
        self.total_cycles_executed = 0
        self.total_flops = 0.0

    @classmethod
    def get_current_device(cls) -> 'VirtualGPU':
        """Singleton accessor for the active virtual GPU."""
        if cls._instance is None:
            cls._instance = VirtualGPU()
        return cls._instance

    @classmethod
    def set_current_device(cls, device: 'VirtualGPU') -> None:
        cls._instance = device

    def get_properties(self) -> DeviceProperties:
        return self.properties

    def synchronize(self) -> None:
        """CUDA cudaDeviceSynchronize equivalent."""
        # Software GPU execution is synchronous / fully synchronized upon dispatch completion
        pass

    def reset(self) -> None:
        """Resets device memory and telemetry."""
        self.memory.reset()
        self.total_kernels_launched = 0
        self.total_draw_calls = 0
        self.total_flops = 0.0

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns runtime performance statistics of the software GPU."""
        return {
            "device_name": self.properties.name,
            "streaming_multiprocessors": self.num_sms,
            "vram_total_mb": self.properties.total_global_mem / (1024 * 1024),
            "vram_allocated_mb": self.memory.allocated_bytes / (1024 * 1024),
            "vram_peak_mb": self.memory.peak_allocated_bytes / (1024 * 1024),
            "kernels_launched": self.total_kernels_launched,
            "draw_calls": self.total_draw_calls,
            "host_to_device_mb": self.memory.total_host_to_device_bytes / (1024 * 1024),
            "device_to_host_mb": self.memory.total_device_to_host_bytes / (1024 * 1024),
            "total_estimated_gflops": self.total_flops / 1e9,
        }
