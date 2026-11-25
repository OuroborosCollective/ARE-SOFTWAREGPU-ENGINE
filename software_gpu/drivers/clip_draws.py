"""Prepare post-vertex color draws for ARE's weighted native command queue.

A draw is a triangle-list pair of clip-space XYZW and smooth RGB Float32
arrays. The supported viewport is the full target, positive height, [0,1]
depth, no face culling. This stage owns no Vulkan handles.
"""
import numpy as np

from software_gpu.drivers.command_submission import record_native_draws
from software_gpu.graphics.geometry import clip_triangle, edge_function
from software_gpu.graphics.native_raster import pack_triangles


def record_clip_draws(draws, width, height):
    """Clip in Vulkan's 0 <= Z <= W volume, preserving primitive order."""
    if (type(width) is not int or type(height) is not int or
            not 1 <= width <= 4096 or not 1 <= height <= 4096 or width * height > 4194304):
        raise ValueError("ARE_CLIP_VIEWPORT")
    if not isinstance(draws, (list, tuple)) or not 1 <= len(draws) <= 256:
        raise ValueError("ARE_CLIP_DRAW_COUNT")

    prepared = {}
    records = []
    input_total = 0
    output_total = 0
    for positions, colors in draws:
        if (type(positions) is not np.ndarray or positions.dtype != np.float32 or
                positions.ndim != 2 or positions.shape[1] != 4 or len(positions) % 3 or
                type(colors) is not np.ndarray or colors.dtype != np.float32 or
                colors.shape != (len(positions), 3)):
            raise ValueError("ARE_CLIP_VERTEX_LAYOUT")
        input_total += len(positions) // 3
        if input_total > 200_000:
            raise ValueError("ARE_CLIP_INPUT_BUDGET")
        if not np.isfinite(positions).all() or not np.isfinite(colors).all():
            raise ValueError("ARE_CLIP_NONFINITE")

        # The cache lives for one submission. Snapshot the actual bound vertex
        # and color bytes, so another submission always sees current inputs.
        key = (positions.tobytes(), colors.tobytes()) if len(positions) <= 96 else None
        if key is not None:
            previous = prepared.get(key)
            if previous is not None:
                output_total += len(previous)
                if output_total > 200_000 or output_total * width * height > 64_000_000:
                    raise ValueError("ARE_CLIP_OUTPUT_BUDGET")
                records.append(previous)
                continue

        triangles = []
        for start in range(0, len(positions), 3):
            primitive = [(positions[i].astype(np.float64), {"color": colors[i]})
                         for i in range(start, start + 3)]
            for clipped in clip_triangle(primitive, zero_to_one=True):
                clip = np.array([point for point, _ in clipped])
                inv_w = 1.0 / clip[:, 3]
                ndc = clip[:, :3] * inv_w[:, None]
                screen = np.empty((3, 3), dtype=np.float32)
                screen[:, 0] = (ndc[:, 0] + 1.0) * (width / 2)
                screen[:, 1] = (ndc[:, 1] + 1.0) * (height / 2)
                screen[:, 2] = ndc[:, 2]
                attrs = [varyings for _, varyings in clipped]
                area = float(edge_function(*screen))
                if area < 0:
                    screen[[1, 2]] = screen[[2, 1]]
                    inv_w[[1, 2]] = inv_w[[2, 1]]
                    attrs[1], attrs[2] = attrs[2], attrs[1]
                    area = float(edge_function(*screen))
                if area <= 1e-9:
                    continue
                output_total += 1
                if output_total > 200_000 or output_total * width * height > 64_000_000:
                    raise ValueError("ARE_CLIP_OUTPUT_BUDGET")
                triangles.append((*screen, *inv_w, *attrs, area))
        packed = pack_triangles(triangles)
        if key is not None:
            prepared[key] = packed
        records.append(packed)
    return record_native_draws(records)
