"""
Core Types and Dimensional Structures for SoftwareGPU.
Implements CUDA/OpenCL compatible grid, block, and thread primitives.
Inspired by MCUDA (Stratton et al.) and PoCL (Jääskeläinen et al.).
"""

from dataclasses import dataclass, field
from typing import Tuple, Union, Any, Optional
import numpy as np


class Dim3:
    """Represents a 3-dimensional integer coordinate or dimension (x, y, z).
    Matches CUDA dim3 / OpenCL work-group dimensions.
    """
    __slots__ = ('x', 'y', 'z')

    def __init__(self, x: Union[int, Tuple[int, ...], 'Dim3'] = 1, y: int = 1, z: int = 1):
        if isinstance(x, Dim3):
            self.x = int(x.x)
            self.y = int(x.y)
            self.z = int(x.z)
        elif isinstance(x, (tuple, list)):
            n = len(x)
            self.x = int(x[0]) if n > 0 else 1
            self.y = int(x[1]) if n > 1 else 1
            self.z = int(x[2]) if n > 2 else 1
        else:
            self.x = int(x)
            self.y = int(y)
            self.z = int(z)

    def total(self) -> int:
        """Total number of elements in the volume."""
        return self.x * self.y * self.z

    def as_tuple(self) -> Tuple[int, int, int]:
        return (self.x, self.y, self.z)

    def __repr__(self) -> str:
        return f"Dim3(x={self.x}, y={self.y}, z={self.z})"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Dim3):
            return self.x == other.x and self.y == other.y and self.z == other.z
        if isinstance(other, (tuple, list)):
            return self.as_tuple() == tuple(other)
        return False


class ThreadContext:
    """Thread execution context inside a SIMT warp/block.
    Provides standard CUDA built-in variables:
    threadIdx, blockIdx, blockDim, gridDim, warpSize.
    """
    __slots__ = (
        'threadIdx', 'blockIdx', 'blockDim', 'gridDim',
        'warp_id', 'lane_id', '_shared_mem', '_barrier_fn'
    )

    def __init__(
        self,
        thread_idx: Dim3,
        block_idx: Dim3,
        block_dim: Dim3,
        grid_dim: Dim3,
        warp_id: int = 0,
        lane_id: int = 0,
        shared_mem: Optional[Any] = None,
        barrier_fn: Optional[Any] = None
    ):
        self.threadIdx = thread_idx
        self.blockIdx = block_idx
        self.blockDim = block_dim
        self.gridDim = grid_dim
        self.warp_id = warp_id
        self.lane_id = lane_id
        self._shared_mem = shared_mem
        self._barrier_fn = barrier_fn

    @property
    def shared(self) -> Any:
        """Access to block-local shared memory (__shared__)."""
        return self._shared_mem

    def syncthreads(self) -> None:
        """CUDA __syncthreads() equivalent.
        Synchronizes all threads within the current thread block.
        """
        if self._barrier_fn is not None:
            self._barrier_fn()


class GPUArray:
    """Represents an array allocated in virtual GPU VRAM.
    Maintains device memory address, shape, dtype, and provides
    transparent bidirectional host-to-device transfers.
    """
    def __init__(
        self,
        shape: Tuple[int, ...],
        dtype: np.dtype = np.float32,
        device_ptr: int = 0,
        memory_manager: Optional[Any] = None,
        initial_data: Optional[np.ndarray] = None
    ):
        self.shape = tuple(shape)
        self.dtype = np.dtype(dtype)
        self.device_ptr = device_ptr
        self.memory_manager = memory_manager
        self.size = int(np.prod(self.shape))
        self.nbytes = self.size * self.dtype.itemsize
        
        # Internal contiguous buffer representing physical backing store in CPU RAM
        if initial_data is not None:
            self._data = np.ascontiguousarray(initial_data, dtype=self.dtype).copy()
        else:
            self._data = np.zeros(self.shape, dtype=self.dtype)

    @property
    def raw_buffer(self) -> np.ndarray:
        """Direct access to backing memory buffer."""
        return self._data

    def copy_to_host(self, dest: Optional[np.ndarray] = None) -> np.ndarray:
        """CUDA cudaMemcpyDeviceToHost equivalent."""
        if dest is not None:
            dest[...] = self._data
            return dest
        return self._data.copy()

    def copy_from_host(self, src: np.ndarray) -> None:
        """CUDA cudaMemcpyHostToDevice equivalent."""
        np.copyto(self._data, src.astype(self.dtype, copy=False))

    def to_numpy(self) -> np.ndarray:
        """Convert to NumPy array on host."""
        return self.copy_to_host()

    def __getitem__(self, item: Any) -> Any:
        return self._data[item]

    def __setitem__(self, item: Any, value: Any) -> None:
        self._data[item] = value

    def __len__(self) -> int:
        return self.shape[0] if self.shape else 0

    def __repr__(self) -> str:
        return f"GPUArray(shape={self.shape}, dtype={self.dtype}, ptr=0x{self.device_ptr:08x})"
