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
                 num_threads: Optional[int] = None, backend: str = "tiles"):
        if not isinstance(tile_size, int) or not 1 <= tile_size <= 256:
            raise ValueError("tile_size must be between 1 and 256 pixels")
        if backend not in ("tiles", "tiles-jit", "bands"):
            raise ValueError("backend must be tiles, tiles-jit or bands")
        if num_threads is not None and (not isinstance(num_threads, int) or num_threads < 1):
            raise ValueError("num_threads must be positive")
        self.fb = framebuffer
        self.tile_size = tile_size
        self.backend = backend
        self.num_threads = num_threads or VirtualGPU.get_current_device().num_sms
        self.executor = ThreadPoolExecutor(max_workers=self.num_threads, thread_name_prefix="SoftGPU_RasterTile")

    def draw_mesh(self, vertices: List[Vertex], indices: List[Tuple[int, int, int]], shader: Shader) -> None:
        """Processes 3D mesh through Vertex Shader -> Clipping -> Rasterization -> Fragment Shader."""
        device = VirtualGPU.get_current_device()
        device.total_draw_calls += 1

        triangles = prepare_triangles(vertices, indices, shader, self.fb.width, self.fb.height)

        if not triangles:
            return

        if self.backend in ("tiles", "tiles-jit"):
            rasterize_tiles(self.fb, triangles, shader, self.tile_size, self.executor,
                            self.num_threads, compiled=self.backend == "tiles-jit")
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

            for py in range(min_y, max_y + 1):
                p_y = py + 0.5
                for px in range(min_x, max_x + 1):
                    p_x = px + 0.5
                    p = np.array([p_x, p_y], dtype=np.float32)

                    # Barycentric coordinates via edge functions
                    w0 = edge_function(s1, s2, p)
                    w1 = edge_function(s2, s0, p)
                    w2 = edge_function(s0, s1, p)

                    # Inside triangle test
                    if (edge_covered(w0, s1, s2) and edge_covered(w1, s2, s0) and
                            edge_covered(w2, s0, s1)):
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
