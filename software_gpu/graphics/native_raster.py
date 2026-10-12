"""Opt-in C++17 raster/VertexColor specialization; Python only at draw boundary.

Build explicitly before rendering. Clipping/packing are still Python/NumPy.
The synchronous native draw owns no buffers, performs no callbacks and must
have exclusive access to the framebuffer until it returns.
"""
import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .batch_shader import VertexColorShader, _NATIVE_VERTEX_COLOR_METHODS
from ..research.native_symbolic import FLAGS, compiler

NATIVE = Path(__file__).resolve().parents[2] / 'native'


def build_raster_kernel(directory):
    """Source-checkout build tool. Does not build implicitly during rendering."""
    target = Path(directory).resolve()
    sources = {name: (NATIVE/name).read_bytes() for name in
               ('raster/core.hpp', 'raster/library.cpp', 'symbolic/core.hpp')}
    for name, content in sources.items():
        path = target/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    binary = target/('raster.dll' if sys.platform == 'win32' else 'raster.so')
    # Include MinGW's thread runtime too; ctypes does not search PATH for DLLs.
    shared = ['-shared', '-static'] if sys.platform == 'win32' else ['-shared', '-fPIC']
    cxx = compiler()
    start = time.perf_counter_ns()
    result = subprocess.run([cxx, *FLAGS, *shared, str(target/'raster/library.cpp'), '-o', str(binary)],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('NATIVE_RASTER_BUILD_FAILED:' + result.stderr[-6000:])
    receipt = {'protocol': 'are.native-raster-build.v1', 'compiler': cxx,
               'compiler_version': subprocess.check_output([cxx, '--version'], text=True).splitlines()[0],
               'flags': [*FLAGS, *shared], 'compile_ms': (time.perf_counter_ns()-start)/1e6,
               'source_sha256': {k: hashlib.sha256(v).hexdigest() for k, v in sources.items()},
               'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
               'compiler_diagnostics': result.stderr}
    (target/'build.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    return binary, receipt


def pack_triangles(triangles):
    """Preserve the tile path's f32 operation order AND mixed clipped RGB dtype."""
    if len(triangles) > 200000:
        raise ValueError('NATIVE_RASTER_TRIANGLE_BUDGET')
    packed = np.empty((len(triangles), 23), dtype=np.float64)
    for row, tri in zip(packed, triangles):
        row[:9] = np.asarray(tri[:3], dtype=np.float32).ravel()
        row[9:12] = np.asarray(tri[3:6], dtype=np.float32)
        row[12] = np.float32(1.0/tri[9])
        mask = 0
        for vertex in range(3):
            color = tri[6+vertex].get('color')
            if (not isinstance(color, np.ndarray) or color.shape != (3,) or
                    color.dtype not in (np.dtype('float32'), np.dtype('float64'))):
                raise ValueError('NATIVE_RASTER_COLOR_DOMAIN')
            weight = color*tri[3+vertex]
            row[13+3*vertex:16+3*vertex] = weight
            mask |= int(weight.dtype == np.float64) << vertex
        row[22] = mask
    return packed


class NativeRasterKernel:
    """Load a trusted, explicitly hash-bound binary. Hashes are not a sandbox."""
    def __init__(self, binary, expected_sha256):
        path = Path(binary).resolve()
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_sha256:
            raise ValueError('NATIVE_RASTER_BINARY_HASH')
        self.binary_sha256 = actual
        self._lib = ctypes.CDLL(str(path))
        self._lib.are_raster_abi.argtypes = []
        self._lib.are_raster_abi.restype = ctypes.c_uint
        if self._lib.are_raster_abi() != 1:
            raise ValueError('NATIVE_RASTER_ABI')
        ptr = ctypes.c_void_p
        size = ctypes.c_size_t
        self._call = self._lib.are_raster_draw
        self._call.argtypes = [ptr, size, size, ctypes.c_int, ctypes.c_int, ptr, size, ptr, size, ptr, size]
        self._call.restype = ctypes.c_int

    @staticmethod
    def validate_shader(shader):
        if (type(shader) is not VertexColorShader or
                tuple(getattr(getattr(shader, name), '__func__', None) for name in
                      ('vertex_shader', 'fragment_shader')) != _NATIVE_VERTEX_COLOR_METHODS):
            raise ValueError('NATIVE_RASTER_SHADER_UNSUPPORTED')

    def draw(self, framebuffer, triangles, shader):
        self.validate_shader(shader)
        width, height = framebuffer.width, framebuffer.height
        if (type(width) is not int or type(height) is not int or
                not 1 <= width <= 4096 or not 1 <= height <= 4096 or width*height > 4194304):
            raise ValueError('NATIVE_RASTER_FRAME_BUDGET')
        color, depth = framebuffer.color_buffer, framebuffer.depth_buffer
        for array, dtype, shape in ((color, np.dtype('uint8'), (height, width, 4)),
                                    (depth, np.dtype('float32'), (height, width))):
            if (type(array) is not np.ndarray or array.dtype != dtype or array.shape != shape or
                    not array.flags.c_contiguous or not array.flags.aligned or not array.flags.writeable):
                raise ValueError('NATIVE_RASTER_BUFFER')
        if np.shares_memory(color, depth):
            raise ValueError('NATIVE_RASTER_BUFFER_ALIAS')
        packed = pack_triangles(triangles)
        counts = np.zeros(3, dtype=np.uint64)
        # CDLL releases the GIL. Caller must not mutate mesh/buffers concurrently.
        status = self._call(packed.ctypes.data, packed.size, len(packed), width, height,
                            color.ctypes.data, color.nbytes, depth.ctypes.data, depth.size,
                            counts.ctypes.data, counts.size)
        if status:
            raise ValueError('NATIVE_RASTER_REJECTED:' + str(status))
        return {'protocol': 'are.native-raster.v1', 'backend': 'native-cpp',
                'binary_sha256': self.binary_sha256, 'workers': 1,
                'prepared_triangles': len(packed), 'candidate_samples': int(counts[0]),
                'covered_samples': int(counts[1]), 'shaded_samples': int(counts[2]),
                'python_fragment_calls': 0, 'python_preparation': True}
