"""
Software GPU Rasterizer based on Mesa llvmpipe and Intel OpenSWR architectures.
Implements tiled multi-threaded rasterization, barycentric edge equations,
early-Z depth testing, and perspective-correct interpolation.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Dict, Any, Optional
import numpy as np

from .framebuffer import Framebuffer
from .shader import Shader, Vertex
from ..core.device import VirtualGPU
from .tile_backend import rasterize_tiles
from .geometry import prepare_triangles, edge_function, edge_covered



class SoftwareRasterizer:
    """CPU renderer with selectable tile and historical band backends.

    The bands backend preserves the previous implementation as a measurable
    reference. Neither backend is a physical GPU or hardware GPU driver.
    """
    def __init__(self, framebuffer: Framebuffer, tile_size: int = 32,
                 num_threads: Optional[int] = None, backend: str = "tiles", plan_policy=None,
                 native_kernel=None, preparation_cache_bytes: int = 0,
                 preparation_cache_entries: int = 8):
        if not isinstance(tile_size, int) or not 1 <= tile_size <= 256:
            raise ValueError("tile_size must be between 1 and 256 pixels")
        if backend not in ("tiles", "tiles-jit", "tiles-plan", "tiles-deferred", "bands", "native-cpp"):
            raise ValueError("backend must be tiles, tiles-jit, tiles-plan, tiles-deferred, bands or native-cpp")
        if num_threads is not None and (not isinstance(num_threads, int) or num_threads < 1):
            raise ValueError("num_threads must be positive")
        if backend == "native-cpp":
            from .native_raster import NativeRasterKernel
            if type(native_kernel) is not NativeRasterKernel or num_threads not in (None, 1):
                raise ValueError("native-cpp requires NativeRasterKernel and one worker")
            num_threads = 1
        elif native_kernel is not None:
            raise ValueError("native_kernel requires native-cpp")
        if (type(preparation_cache_bytes) is not int or preparation_cache_bytes < 0
                or type(preparation_cache_entries) is not int or preparation_cache_entries < 1):
            raise ValueError("PREPARATION_CACHE_BUDGET_INVALID")
        if preparation_cache_bytes and backend not in ("tiles", "tiles-plan"):
            raise ValueError("PREPARATION_CACHE_REQUIRES_NUMPY_TILES")
        if plan_policy is not None:
            from .surface_plan import SurfacePlanPolicy
            if backend != "tiles-plan" or not isinstance(plan_policy, SurfacePlanPolicy):
                raise ValueError("plan_policy requires tiles-plan and SurfacePlanPolicy")
        self.fb = framebuffer
        self.tile_size = tile_size
        self.backend = backend
        self.plan_policy = plan_policy
        self.last_plan_receipt = None
        self.last_deferred_receipt = None
        self.native_kernel = native_kernel
        self.last_native_receipt = None
        self.last_preparation_receipt = None
        self.preparation_cache = None
        if preparation_cache_bytes:
            from .preparation_cache import PreparationCache
            self.preparation_cache = PreparationCache(preparation_cache_bytes, preparation_cache_entries)
        self.num_threads = num_threads or VirtualGPU.get_current_device().num_sms
        self.executor = ThreadPoolExecutor(max_workers=self.num_threads, thread_name_prefix="SoftGPU_RasterTile")

    def draw_mesh(self, vertices: List[Vertex], indices: List[Tuple[int, int, int]], shader: Shader) -> None:
        """Processes 3D mesh through Vertex Shader -> Clipping -> Rasterization -> Fragment Shader."""
        device = VirtualGPU.get_current_device()
        device.total_draw_calls += 1

        self.last_plan_receipt = None
        self.last_deferred_receipt = None
        self.last_native_receipt = None
        if self.native_kernel is not None:
            self.native_kernel.validate_shader(shader)
        self.last_preparation_receipt = None
        prepared_bins = None
        if self.preparation_cache is None:
            triangles = prepare_triangles(vertices, indices, shader, self.fb.width, self.fb.height)
        else:
            scan_min_samples = None
            if self.backend == "tiles-plan":
                from .surface_plan import DEFAULT_PLAN_POLICY
                scan_min_samples = (self.plan_policy or DEFAULT_PLAN_POLICY).scan_min_samples
            prepared, self.last_preparation_receipt = self.preparation_cache.prepare(
                vertices, indices, shader, self.fb.width, self.fb.height,
                self.tile_size, scan_min_samples)
            triangles, prepared_bins = prepared.triangles, prepared.bins
        if self.native_kernel is not None:
            self.last_native_receipt = self.native_kernel.draw(self.fb, triangles, shader)
            return
        if self.backend == "tiles-deferred":
            from .deferred_visibility import rasterize_deferred, validate_deferred_shader
            # Fail closed before rendering, even for empty draws.
            validate_deferred_shader(shader)
            self.last_deferred_receipt = rasterize_deferred(
                self.fb, triangles, shader, self.tile_size, self.executor,
                self.num_threads)
            return
        if self.backend in ("tiles", "tiles-jit", "tiles-plan"):
            self.last_plan_receipt = rasterize_tiles(
                self.fb, triangles, shader, self.tile_size, self.executor,
                self.num_threads, compiled=self.backend == "tiles-jit",
                planned=self.backend == "tiles-plan", plan_policy=self.plan_policy,
                prepared_bins=prepared_bins)
            return

        if not triangles:
            return

        # Historical horizontal-band reference renderer (not actual tile binning).
        num_bands = min(self.num_threads, max(1, self.fb.height // self.tile_size))
        band_height = (self.fb.height + num_bands - 1) // num_bands

        bands = [
            (i * band_height, min((i + 1) * band_height, self.fb.height))
            for i in range(num_bands)
        ]

        futures = []
        for y_start, y_end in bands:
            futures.append(self.executor.submit(self._rasterize_band, triangles, shader, y_start, y_end))

        for f in futures:
            f.result()

    def _rasterize_band(self, triangles: list, shader: Shader, y_start: int, y_end: int) -> None:
        """Rasterizes triangles that overlap the vertical band [y_start, y_end)."""
        fb_w = self.fb.width
        for (s0, s1, s2, inv_w0, inv_w1, inv_w2, v0_var, v1_var, v2_var, area) in triangles:
            # Triangle 2D bounding box
            min_x = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
            max_x = min(fb_w - 1, int(np.ceil(max(s0[0], s1[0], s2[0]))))
            min_y = max(y_start, int(np.floor(min(s0[1], s1[1], s2[1]))))
            max_y = min(y_end - 1, int(np.ceil(max(s0[1], s1[1], s2[1]))))

            if min_x > max_x or min_y > max_y:
                continue

            inv_area = 1.0 / area

            # PERFORMANCE: Precomputing edge deltas and explicitly evaluating w0/w1/w2
            # eliminates inner-loop np.array() allocations and edge_function() calls.
            # Avoid incremental additions which lose float32 byte-parity over width.
            # Expected impact: >10x speedup in bounding box rasterization.
            s1_x, s1_y = s1[0], s1[1]
            s2_x, s2_y = s2[0], s2[1]
            s0_x, s0_y = s0[0], s0[1]

            e0_x = s2_x - s1_x
            e0_y = s2_y - s1_y
            e1_x = s0_x - s2_x
            e1_y = s0_y - s2_y
            e2_x = s1_x - s0_x
            e2_y = s1_y - s0_y

            c0 = (float(e0_y) > 0.0) or (float(e0_y) == 0.0 and float(e0_x) < 0.0)
            c1 = (float(e1_y) > 0.0) or (float(e1_y) == 0.0 and float(e1_x) < 0.0)
            c2 = (float(e2_y) > 0.0) or (float(e2_y) == 0.0 and float(e2_x) < 0.0)

            for py in range(min_y, max_y + 1):
                p_y = py + 0.5

                w0_y_part = (p_y - s1_y) * e0_x
                w1_y_part = (p_y - s2_y) * e1_x
                w2_y_part = (p_y - s0_y) * e2_x

                for px in range(min_x, max_x + 1):
                    p_x = px + 0.5

                    w0 = (p_x - s1_x) * e0_y - w0_y_part
                    w1 = (p_x - s2_x) * e1_y - w1_y_part
                    w2 = (p_x - s0_x) * e2_y - w2_y_part

                    if not ((w0 >= 0) if c0 else (w0 > 0)):
                        continue

                    if not ((w1 >= 0) if c1 else (w1 > 0)):
                        continue

                    if not ((w2 >= 0) if c2 else (w2 > 0)):
                        continue

                    alpha = w0 * inv_area
                    beta = w1 * inv_area
                    gamma = w2 * inv_area

                    # Interpolate depth Z (screen space)
                    z_val = alpha * s0[2] + beta * s1[2] + gamma * s2[2]

                    # Early-Z depth test
                    if z_val < self.fb.depth_buffer[py, px]:
                        # Perspective-correct interpolation factor
                        interp_inv_w = alpha * inv_w0 + beta * inv_w1 + gamma * inv_w2
                        interp_factor = 1.0 / interp_inv_w if interp_inv_w > 1e-9 else 1.0

                        # Interpolate varying attributes
                        interpolated_varyings = {}
                        for k in v0_var:
                            val0, val1, val2 = v0_var[k], v1_var[k], v2_var[k]
                            if isinstance(val0, np.ndarray):
                                weighted = (
                                    alpha * (val0 * inv_w0) +
                                    beta * (val1 * inv_w1) +
                                    gamma * (val2 * inv_w2)
                                ) * interp_factor
                                interpolated_varyings[k] = weighted
                            else:
                                interpolated_varyings[k] = val0

                        # Fragment Shader Invocation
                        r, g, b, a = shader.fragment_shader(interpolated_varyings)

                        # Update Framebuffer and Depth buffer
                        self.fb.depth_buffer[py, px] = z_val
                        self.fb.color_buffer[py, px, 0] = r
                        self.fb.color_buffer[py, px, 1] = g
                        self.fb.color_buffer[py, px, 2] = b
                        self.fb.color_buffer[py, px, 3] = a
