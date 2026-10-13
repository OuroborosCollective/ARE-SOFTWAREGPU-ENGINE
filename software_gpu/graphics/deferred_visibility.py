"""Opt-in visibility-first tiled rasterizer for the strictly pure vertex-color shader.

Experimental per-draw visibility resolve only. Each tile processes submitted
triangles in order with exactly the NumPy edge/depth expression from tiles.
Deferred shading is restricted to a known pure implementation, never arbitrary
fragment callbacks or multi-draw deferral. Not a hardware GPU implementation.
"""
from __future__ import annotations

from concurrent.futures import Executor
import numpy as np

from .batch_shader import VertexColorShader
from .geometry import edge_covered
from .surface_plan import checked_batch_rgba
from .tile_backend import bin_triangles

PROTOCOL = "are.deferred-visibility.v1"


def validate_deferred_shader(shader):
    """Do not alter callback ordering for arbitrary/mutable shader semantics."""
    if (type(shader) is not VertexColorShader
            or getattr(shader.vertex_shader, "__func__", None) is not VertexColorShader.vertex_shader
            or getattr(shader.fragment_shader, "__func__", None) is not VertexColorShader.fragment_shader
            or getattr(shader.fragment_shader_batch, "__func__", None)
            is not VertexColorShader.fragment_shader_batch
            or getattr(shader, "batch_fragment_equivalent_to", None)
            is not VertexColorShader.fragment_shader):
        raise ValueError("DEFERRED_SHADER_NOT_PURE")


def rasterize_deferred(fb, triangles, shader, tile_size, executor: Executor, workers):
    """Keep last strict-depth winner per pixel, then shade each winner once.

    This is one draw's visibility resolve, not a whole-frame deferred pipeline:
    multiple draw_mesh calls commit between calls. Pixel ownership is disjoint
    per tile, and ties keep the first submitted candidate. No float32 shortcut.
    """
    validate_deferred_shader(shader)
    prepared = bin_triangles(triangles, fb.width, fb.height, tile_size)
    tasks = prepared.tasks

    def draw_tile(task):
        (ty, tx), candidates = task
        x0, y0 = tx * tile_size, ty * tile_size
        x1 = min(fb.width, x0 + tile_size)
        y1 = min(fb.height, y0 + tile_size)
        scratch_depth = fb.depth_buffer[y0:y1, x0:x1].copy()
        winner = np.full(scratch_depth.shape, -1, dtype=np.int32)
        # The candidate arrays retain original NumPy scalar dtypes/operation
        # order across both clipped and unclipped triangle setup.
        candidates_values = []
        depth_passes = 0
        for index, (tri, bx0, bx1, by0, by1) in enumerate(candidates):
            left, right = max(bx0, x0), min(bx1, x1 - 1)
            top, bottom = max(by0, y0), min(by1, y1 - 1)
            if left > right or top > bottom:
                candidates_values.append(None)
                continue
            s0, s1, s2, iw0, iw1, iw2, v0, v1, v2, area = tri
            inv_area = 1.0 / area
            px = (np.arange(left, right + 1, dtype=np.float32) + np.float32(.5))[None, :]
            py = (np.arange(top, bottom + 1, dtype=np.float32) + np.float32(.5))[:, None]
            w0 = (px - s1[0]) * (s2[1] - s1[1]) - (py - s1[1]) * (s2[0] - s1[0])
            w1 = (px - s2[0]) * (s0[1] - s2[1]) - (py - s2[1]) * (s0[0] - s2[0])
            w2 = (px - s0[0]) * (s1[1] - s0[1]) - (py - s0[1]) * (s1[0] - s0[0])
            covered = (edge_covered(w0, s1, s2)
                       & edge_covered(w1, s2, s0)
                       & edge_covered(w2, s0, s1))
            if not covered.any():
                candidates_values.append(None)
                continue
            alpha, beta, gamma = w0 * inv_area, w1 * inv_area, w2 * inv_area
            depth = alpha * s0[2] + beta * s1[2] + gamma * s2[2]
            offset_y, offset_x = top - y0, left - x0
            h, w = depth.shape
            local_depth = scratch_depth[offset_y:offset_y+h, offset_x:offset_x+w]
            visible = covered & (depth < local_depth)
            rows, cols = np.nonzero(visible)
            if len(rows):
                depth_passes += len(rows)
                ry, rx = rows + offset_y, cols + offset_x
                # Same per-candidate assignment as the reference: strictly <.
                scratch_depth[ry, rx] = depth[rows, cols]
                winner[ry, rx] = index
            candidates_values.append((rows + offset_y, cols + offset_x,
                                      alpha[rows, cols], beta[rows, cols],
                                      gamma[rows, cols], tri))
        batch_calls = 0
        shaded = 0
        # Commit the winning depth from identical NumPy depth values. The
        # framebuffer remains unchanged until the visibility pass completes.
        fb.depth_buffer[y0:y1, x0:x1] = scratch_depth
        for index, entry in enumerate(candidates_values):
            if entry is None:
                continue
            all_rows, all_cols, aa, bb, cc, tri = entry
            is_winner = winner[all_rows, all_cols] == index
            if not is_winner.any():
                continue
            rows, cols = all_rows[is_winner], all_cols[is_winner]
            aa, bb, cc = aa[is_winner], bb[is_winner], cc[is_winner]
            _, _, _, iw0, iw1, iw2, v0, v1, v2, _ = tri
            iw_all = aa * iw0 + bb * iw1 + cc * iw2
            factor_all = np.divide(1.0, iw_all, out=np.ones_like(iw_all),
                                   where=iw_all > 1e-9)
            varyings = {}
            for key in v0:
                va, vb, vc = v0[key], v1[key], v2[key]
                if isinstance(va, np.ndarray):
                    varyings[key] = ((aa[:, None] * (va * iw0)
                                      + bb[:, None] * (vb * iw1)
                                      + cc[:, None] * (vc * iw2))
                                     * factor_all[:, None])
                else:
                    varyings[key] = va
            rgba = checked_batch_rgba(shader.fragment_shader_batch, varyings, len(rows))
            fb.color_buffer[y0 + rows, x0 + cols, :] = rgba
            shaded += len(rows)
            batch_calls += 1
        return depth_passes, shaded, batch_calls

    # Bounded task groups; color/depth regions never overlap between groups.
    if workers == 1 or len(tasks) <= 1:
        results = [draw_tile(task) for task in tasks]
    else:
        groups = [[] for _ in range(min(workers, len(tasks)))]
        for i, task in enumerate(tasks):
            groups[i % len(groups)].append(task)

        def run_group(group):
            return [draw_tile(task) for task in group]

        futures = [executor.submit(run_group, group) for group in groups]
        results = [result for future in futures for result in future.result()]
    candidates_total = sum(result[0] for result in results)
    shaded_total = sum(result[1] for result in results)
    return {
        "protocol": PROTOCOL, "authority": "derived-render-only",
        "tiles": len(tasks), "workers": workers,
        "candidate_depth_passes": int(candidates_total),
        "final_shaded_samples": int(shaded_total),
        "avoided_fragment_invocations": int(candidates_total - shaded_total),
        "batch_fragment_calls": int(sum(result[2] for result in results)),
        "limits": ["known-pure-vertex-color-only", "single-draw-visibility",
                   "no-hardware-gpu-parity", "experimental-no-speedup-claim"],
    }
