"""CPU-only tile-binned raster stage.

Tiles own disjoint framebuffer regions. Triangle lists retain submission order,
so Z-buffer and blending callbacks remain ordered within each tile. NumPy
handles coverage/depth masks; arbitrary Python fragment shaders remain scalar.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import Executor
from typing import Any

import numpy as np


def rasterize_tiles(fb: Any, triangles: list, shader: Any, tile_size: int,
                    executor: Executor, workers: int, compiled: bool = False) -> None:
    """Bin triangles by 2-D tiles, then shade each independent tile in order.

    This is a CPU vectorized coverage/depth backend, *not* compiled SIMD shader
    execution. Workers can safely write separate tiles of the same framebuffer.
    """
    bins = defaultdict(list)
    frame_w, frame_h = fb.width, fb.height
    for tri in triangles:
        s0, s1, s2 = tri[:3]
        x0 = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
        x1 = min(frame_w - 1, int(np.ceil(max(s0[0], s1[0], s2[0]))))
        y0 = max(0, int(np.floor(min(s0[1], s1[1], s2[1]))))
        y1 = min(frame_h - 1, int(np.ceil(max(s0[1], s1[1], s2[1]))))
        if x0 > x1 or y0 > y1:
            continue
        # Row-major deterministic tile iteration; no per-pixel bin storage.
        for ty in range(y0 // tile_size, y1 // tile_size + 1):
            for tx in range(x0 // tile_size, x1 // tile_size + 1):
                bins[(ty, tx)].append((tri, x0, x1, y0, y1))

    if not bins:
        return

    # Lazy optional native kernel, intentionally never loaded by the default
    # NumPy backend. Fragment shader callbacks stay outside the JIT boundary.
    kernel = None
    if compiled:
        from .compiled_tile import get_compiled_coverage
        kernel = get_compiled_coverage()

    def draw_tile(task):
        (ty, tx), candidates = task
        tile_x0, tile_y0 = tx * tile_size, ty * tile_size
        tile_x1 = min(frame_w - 1, tile_x0 + tile_size - 1)
        tile_y1 = min(frame_h - 1, tile_y0 + tile_size - 1)
        for tri, x0, x1, y0, y1 in candidates:
            left, right = max(x0, tile_x0), min(x1, tile_x1)
            top, bottom = max(y0, tile_y0), min(y1, tile_y1)
            if left > right or top > bottom:
                continue
            (s0, s1, s2, iw0, iw1, iw2, v0, v1, v2, area) = tri
            inv_area = 1.0 / area
            depth_tile = fb.depth_buffer[top:bottom+1, left:right+1]
            if kernel is not None:
                # LLVM-compiled, GIL-free CPU inner loop. Subpixel/interpolation
                # order remains deterministic and float32 precision is retained.
                rows, cols, aa, bb, cc, zz = kernel(
                    s0, s1, s2, left, right, top, bottom, inv_area, depth_tile
                )
            else:
                # Native compiled NumPy ufuncs process coverage/depth by tile.
                px = (np.arange(left, right + 1, dtype=np.float32) + np.float32(0.5))[None, :]
                py = (np.arange(top, bottom + 1, dtype=np.float32) + np.float32(0.5))[:, None]
                w0 = (px - s1[0]) * (s2[1] - s1[1]) - (py - s1[1]) * (s2[0] - s1[0])
                w1 = (px - s2[0]) * (s0[1] - s2[1]) - (py - s2[1]) * (s0[0] - s2[0])
                w2 = (px - s0[0]) * (s1[1] - s0[1]) - (py - s0[1]) * (s1[0] - s0[0])
                covered = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
                if not covered.any():
                    continue
                alpha = w0 * inv_area
                beta = w1 * inv_area
                gamma = w2 * inv_area
                depth = alpha * s0[2] + beta * s1[2] + gamma * s2[2]
                visible = covered & (depth < depth_tile)
                rows, cols = np.nonzero(visible)  # row-major pixel order
                aa, bb, cc, zz = alpha[rows, cols], beta[rows, cols], gamma[rows, cols], depth[rows, cols]
            for row, col, a, b, c, z_value in zip(rows, cols, aa, bb, cc, zz):
                iy, ix = int(row) + top, int(col) + left
                iw = a * iw0 + b * iw1 + c * iw2
                factor = 1.0 / iw if iw > 1e-9 else 1.0
                varyings = {}
                for key in v0:
                    va, vb, vc = v0[key], v1[key], v2[key]
                    if isinstance(va, np.ndarray):
                        varyings[key] = (a * (va * iw0) + b * (vb * iw1) + c * (vc * iw2)) * factor
                    else:
                        varyings[key] = va
                rgba = shader.fragment_shader(varyings)
                fb.depth_buffer[iy, ix] = z_value
                fb.color_buffer[iy, ix, :] = rgba

    tasks = sorted(bins.items())
    if workers == 1 or len(tasks) == 1:
        for task in tasks:
            draw_tile(task)
    else:
        # A bounded worker submission avoids a future per tile on large frames.
        groups = [[] for _ in range(min(workers, len(tasks)))]
        for i, task in enumerate(tasks):
            groups[i % len(groups)].append(task)

        def draw_group(group):
            for task in group:
                draw_tile(task)

        futures = [executor.submit(draw_group, group) for group in groups]
        for future in futures:
            future.result()
