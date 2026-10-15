"""CPU-only tile-binned raster stage.

Tiles own disjoint framebuffer regions. Triangle lists retain submission order,
so Z-buffer and blending callbacks remain ordered within each tile. NumPy
handles coverage/depth masks; arbitrary Python fragment shaders remain scalar.
"""

from __future__ import annotations

from collections import defaultdict
from collections import Counter
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any

import numpy as np
from .geometry import edge_covered


def _pair_features(x0, x1, y0, y1, tile_size, scan_min_samples):
    """Count bounded rectangles in O(1), without a second pass over every bin."""
    nx, ny = x1 // tile_size - x0 // tile_size + 1, y1 // tile_size - y0 // tile_size + 1
    pairs = nx * ny
    if min(x1 - x0 + 1, tile_size) * min(y1 - y0 + 1, tile_size) < scan_min_samples:
        return pairs, pairs

    def extents(start, end, count):
        if count == 1:
            return {end - start + 1: 1}
        values = Counter((tile_size - start % tile_size, end % tile_size + 1))
        if count > 2:
            values[tile_size] += count - 2
        return values

    widths, heights = extents(x0, x1, nx), extents(y0, y1, ny)
    return pairs, sum(nw * nh for w, nw in widths.items() for h, nh in heights.items()
                      if w * h < scan_min_samples)


@dataclass(frozen=True)
class TileBins:
    """Prepared candidate order only; no coverage, visibility or depth results."""
    triangles: Any
    width: int
    height: int
    tile_size: int
    scan_min_samples: Any
    tasks: tuple
    bbox_samples: int
    binned_pairs: int
    small_pairs: int


def bin_triangles(triangles, width, height, tile_size, scan_min_samples=None):
    """Pure setup shared by uncached draws and the explicit preparation cache."""
    bins = defaultdict(list)
    bbox_samples = 0
    binned_pairs = 0
    small_pairs = 0
    frame_w, frame_h = width, height
    for tri in triangles:
        s0, s1, s2 = tri[:3]
        x0 = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
        x1 = min(frame_w - 1, int(np.ceil(max(s0[0], s1[0], s2[0]))))
        y0 = max(0, int(np.floor(min(s0[1], s1[1], s2[1]))))
        y1 = min(frame_h - 1, int(np.ceil(max(s0[1], s1[1], s2[1]))))
        if x0 > x1 or y0 > y1:
            continue
        if scan_min_samples is not None:
            bbox_samples += (x1 - x0 + 1) * (y1 - y0 + 1)
            # Pre-execution gate features: pair count and pairs below the scan
            # threshold, using the same clipped bounds draw_tile derives.
            pairs, small = _pair_features(x0, x1, y0, y1, tile_size, scan_min_samples)
            binned_pairs += pairs
            small_pairs += small
        # Row-major deterministic tile iteration; no per-pixel bin storage.
        for ty in range(y0 // tile_size, y1 // tile_size + 1):
            for tx in range(x0 // tile_size, x1 // tile_size + 1):
                bins[(ty, tx)].append((tri, x0, x1, y0, y1))

    tasks = tuple((coordinate, tuple(candidates)) for coordinate, candidates in sorted(bins.items()))
    return TileBins(triangles, width, height, tile_size, scan_min_samples,
                    tasks, bbox_samples, binned_pairs, small_pairs)


def rasterize_tiles(fb: Any, triangles: list, shader: Any, tile_size: int,
                    executor: Executor, workers: int, compiled: bool = False,
                    planned: bool = False, plan_policy=None, prepared_bins=None):
    """Bin triangles by 2-D tiles, then shade each independent tile in order.

    This is a CPU vectorized coverage/depth backend, *not* compiled SIMD shader
    execution. Workers can safely write separate tiles of the same framebuffer.
    """
    if planned and compiled:
        raise ValueError("PLANNED_JIT_COMBINATION_UNSUPPORTED")
    requested_plan = planned
    scan_min_samples = None
    if planned:
        from .surface_plan import (PlanTrace, classify_tile, equivalent_batch,
                                   checked_batch_rgba, SurfacePlanPolicy, DEFAULT_PLAN_POLICY,
                                   ADAPTIVE_MAX_TRIANGLES)
        policy = plan_policy if plan_policy is not None else DEFAULT_PLAN_POLICY
        if not isinstance(policy, SurfacePlanPolicy):
            raise ValueError("SURFACE_PLAN_POLICY_INVALID")
        scan_min_samples = policy.scan_min_samples
    prepared = (bin_triangles(triangles, fb.width, fb.height, tile_size, scan_min_samples)
                if prepared_bins is None else prepared_bins)
    if (not isinstance(prepared, TileBins) or prepared.triangles is not triangles
            or (prepared.width, prepared.height, prepared.tile_size, prepared.scan_min_samples)
            != (fb.width, fb.height, tile_size, scan_min_samples)):
        raise ValueError("PREPARED_TILE_BINS_MISMATCH")
    tasks = prepared.tasks
    frame_w, frame_h = fb.width, fb.height
    bbox_samples, binned_pairs, small_pairs = (prepared.bbox_samples,
                                              prepared.binned_pairs, prepared.small_pairs)

    trace = None
    batch = None
    if planned:
        reason = None
        if policy.selection == "adaptive":
            # Only static pre-draw facts are admissible: never time current draws.
            if not tasks:
                reason = "adaptive-no-binned-work"
            elif equivalent_batch(shader) is None:
                reason = "adaptive-no-batch-equivalence"
            elif len(triangles) > ADAPTIVE_MAX_TRIANGLES:
                reason = "adaptive-dense-triangle-count"
            elif bbox_samples < policy.draw_min_bbox_samples_per_triangle * len(triangles):
                reason = "adaptive-insufficient-bbox"
        elif tasks and bbox_samples < policy.draw_min_bbox_samples_per_triangle * len(triangles):
            reason = "small-primitive-cost-threshold"
        planned = reason is None
        trace = PlanTrace(tuple(coordinate for coordinate, _ in tasks), reason, bbox_samples, len(triangles),
                          binned_pairs, small_pairs, policy=policy)
        if planned:
            batch = equivalent_batch(shader)
    if not tasks:
        return trace.receipt() if trace is not None else None

    # Lazy optional native kernel, intentionally never loaded by the default
    # NumPy backend. Fragment shader callbacks stay outside the JIT boundary.
    kernel = None
    if compiled:
        from .compiled_tile import get_compiled_coverage
        kernel = get_compiled_coverage()

    def draw_tile(task):
        (ty, tx), candidates = task
        counts = Counter() if planned else None
        tile_x0, tile_y0 = tx * tile_size, ty * tile_size
        tile_x1 = min(frame_w - 1, tile_x0 + tile_size - 1)
        tile_y1 = min(frame_h - 1, tile_y0 + tile_size - 1)
        for tri, x0, x1, y0, y1 in candidates:
            left, right = max(x0, tile_x0), min(x1, tile_x1)
            top, bottom = max(y0, tile_y0), min(y1, tile_y1)
            if left > right or top > bottom:
                continue
            (s0, s1, s2, iw0, iw1, iw2, v0, v1, v2, area) = tri
            mode = "boundary"
            if planned:
                samples = (right - left + 1) * (bottom - top + 1)
                if samples >= policy.scan_min_samples:
                    mode = classify_tile(s0, s1, s2, left, right, top, bottom)
                    counts["corner_edge_evaluations"] += 12
                    counts[mode] += 1
                    if mode == "outside":
                        counts["skipped_samples"] += samples
                        continue
                else:
                    counts["scan_bypassed"] += 1
                counts["dense_edge_evaluations"] += 3 * samples
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
                if planned and mode == "inside":
                    covered = True
                else:
                    covered = edge_covered(w0, s1, s2) & edge_covered(w1, s2, s0) & edge_covered(w2, s0, s1)
                    if not covered.any():
                        continue
                alpha = w0 * inv_area
                beta = w1 * inv_area
                gamma = w2 * inv_area
                depth = alpha * s0[2] + beta * s1[2] + gamma * s2[2]
                visible = covered & (depth < depth_tile)
                rows, cols = np.nonzero(visible)  # row-major pixel order
                aa, bb, cc, zz = alpha[rows, cols], beta[rows, cols], gamma[rows, cols], depth[rows, cols]
            # Vectorized varying pre-pass: the same elementwise math as the
            # former per-pixel Python loop (inverse-W weighting, perspective
            # factor), evaluated as whole arrays. Per-pixel results are
            # bit-identical; only the scalar per-pixel dict/interpolation
            # overhead is removed. Measured 1.27-1.93x on the phase-4 scenes.
            if planned and len(rows) == 0:
                continue
            iw_all = aa * iw0 + bb * iw1 + cc * iw2
            factor_all = np.divide(1.0, iw_all, out=np.ones_like(iw_all),
                                   where=iw_all > 1e-9)
            flat_varyings = {}
            array_varyings = {}
            for key in v0:
                va, vb, vc = v0[key], v1[key], v2[key]
                if isinstance(va, np.ndarray):
                    if requested_plan:
                        # A sample axis plus the original varying shape,
                        # including scalar ndarrays and matrix/tensor varyings.
                        shape = (-1,) + (1,) * va.ndim
                        array_varyings[key] = (
                            aa.reshape(shape) * (va * iw0)
                            + bb.reshape(shape) * (vb * iw1)
                            + cc.reshape(shape) * (vc * iw2)
                        ) * factor_all.reshape(shape)
                        continue
                    array_varyings[key] = (
                        aa[:, None] * (va * iw0)
                        + bb[:, None] * (vb * iw1)
                        + cc[:, None] * (vc * iw2)
                    ) * factor_all[:, None]
                else:
                    flat_varyings[key] = va
            if planned:
                counts["shaded_samples"] += len(rows)
            if planned and batch is not None and len(rows) >= policy.batch_min_samples:
                varyings = dict(flat_varyings)
                varyings.update(array_varyings)
                rgba = checked_batch_rgba(batch, varyings, len(rows))
                fb.depth_buffer[rows + top, cols + left] = zz
                fb.color_buffer[rows + top, cols + left, :] = rgba
                counts["batch_fragment_calls"] += 1
                counts["batch_fragment_samples"] += len(rows)
                continue
            if planned:
                counts["scalar_fragment_calls"] += len(rows)
            for i in range(len(rows)):
                varyings = dict(flat_varyings)
                for key, values in array_varyings.items():
                    varyings[key] = values[i]
                iy, ix = int(rows[i]) + top, int(cols[i]) + left
                rgba = shader.fragment_shader(varyings)
                fb.depth_buffer[iy, ix] = zz[i]
                fb.color_buffer[iy, ix, :] = rgba
        if trace is not None and planned:
            trace.record((ty, tx), counts)

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
    return trace.receipt() if trace is not None else None
