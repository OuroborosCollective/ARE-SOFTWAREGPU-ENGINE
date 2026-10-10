"""Shared homogeneous clipping, triangle assembly and top-left fill contract.

The bundled Matrix4.perspective uses OpenGL-style clip coordinates:
    -w <= x,y,z <= w, w > 0.
This is a *software* rasterization convention, not native Direct3D compliance.

All raster backends (band, NumPy tiles, LLVM tiles, 4x MSAA) consume the same
clipped triangles and positive-area winding and must observe the same edge rule.
"""

from __future__ import annotations

import numpy as np


_MIN_W = 1.0e-7


def edge_function(a: np.ndarray, b: np.ndarray, p: np.ndarray):
    """Positive on the right of edge a->b in screen-down coordinates."""
    return (p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])


def is_top_left(a: np.ndarray, b: np.ndarray) -> bool:
    """Inclusive edge for positive-area, clockwise screen-space triangles."""
    dy, dx = float(b[1] - a[1]), float(b[0] - a[0])
    return dy > 0.0 or (dy == 0.0 and dx < 0.0)


def edge_covered(value, a: np.ndarray, b: np.ndarray):
    """Top-left rule avoids double shading and cracks on shared edges."""
    return (value > 0) | ((value == 0) & is_top_left(a, b))


def _distance(position: np.ndarray, plane: int) -> float:
    x, y, z, w = position
    if plane == 0:
        return w + x
    if plane == 1:
        return w - x
    if plane == 2:
        return w + y
    if plane == 3:
        return w - y
    if plane == 4:
        return w + z
    if plane == 5:
        return w - z
    return w - _MIN_W


def _interpolate(first, second, fraction: float):
    p0, attrs0 = first
    p1, attrs1 = second
    pos = p0 + fraction * (p1 - p0)
    # Legacy scalar varyings are flat (use the first provoking attribute).
    attrs = {
        key: (attrs0[key] + fraction * (attrs1[key] - attrs0[key])
              if isinstance(attrs0[key], np.ndarray) else attrs0[key])
        for key in attrs0
    }
    return pos, attrs


def clip_triangle(vertices: list[tuple[np.ndarray, dict]]):
    """Sutherland-Hodgman clip against all six homogeneous frustum planes.

    A final w>=epsilon plane ensures projective division stays well-defined.
    Returns zero or more triangles with interpolated *clip-space* varyings.
    """
    polygon = list(vertices)
    for plane in range(7):
        if not polygon:
            break
        output = []
        previous = polygon[-1]
        previous_distance = _distance(previous[0], plane)
        previous_inside = previous_distance >= 0.0
        for current in polygon:
            current_distance = _distance(current[0], plane)
            current_inside = current_distance >= 0.0
            if previous_inside != current_inside:
                fraction = previous_distance / (previous_distance - current_distance)
                output.append(_interpolate(previous, current, fraction))
            if current_inside:
                output.append(current)
            previous = current
            previous_distance = current_distance
            previous_inside = current_inside
        polygon = output

    if len(polygon) < 3:
        return []
    # A triangle clipped by convex planes produces a convex polygon; preserve
    # winding and split into a triangle fan without reordering source faces.
    return [(polygon[0], polygon[i], polygon[i + 1])
            for i in range(1, len(polygon) - 1)]


def prepare_triangles(vertices, indices, shader, width: int, height: int):
    """Build front-facing, clipped, finite screen-space triangles for CPU renderers.

    Invalid positions/varying numbers fail closed by discarding that primitive.
    Invalid mesh *indices* are programming errors and raise IndexError.

    Implementation: batch setup (AeroRaster/GLimpSW style). Plane distances,
    perspective divide, screen mapping and the signed area are evaluated as
    whole arrays over all faces; only faces that actually cross a plane enter
    the per-face Sutherland–Hodgman slow path. Output tuples are bit-identical
    to per-face evaluation (pinned by test_prepare_triangles_setup.py against
    the verbatim original as oracle). Measured 11.6–12.2x faster setup,
    1.08–1.60x end-to-end on 0.4k/5k-triangle scenes at 128–256 px.
    """
    transformed = []
    for vertex in vertices:
        position, attrs = shader.vertex_shader(vertex)
        pos = np.asarray(position, dtype=np.float64)
        if pos.shape != (4,) or not np.isfinite(pos).all():
            transformed.append(None)
            continue
        if not isinstance(attrs, dict):
            raise TypeError("vertex shader varyings must be a dict")
        if any(
            isinstance(value, np.ndarray) and not np.isfinite(value).all()
            for value in attrs.values()
        ):
            transformed.append(None)
            continue
        transformed.append((pos, attrs))

    n_vertices = len(transformed)
    indices = list(indices)
    if not indices:
        return []
    try:
        idx = np.asarray(indices)
        if idx.dtype.kind not in "iu" or idx.ndim != 2 or idx.shape[1] != 3:
            raise ValueError("malformed")
        idx = idx.astype(np.int64, copy=False)
    except (ValueError, TypeError):
        # Reproduce the original fail-fast error for malformed face records.
        for face in indices:
            if len(face) != 3 or any(
                not isinstance(i, (int, np.integer)) for i in face
            ):
                raise IndexError("triangle index outside vertex array")
        raise IndexError("triangle index outside vertex array")
    if idx.min() < 0 or idx.max() >= n_vertices:
        raise IndexError("triangle index outside vertex array")

    valid = np.array([t is not None for t in transformed])
    face_ok = valid[idx].all(axis=1)

    # Stacked clip positions (NaN rows for discarded vertices; those faces are
    # excluded by face_ok and never take the fast path).
    pos_arr = np.array(
        [t[0] if t is not None else np.full(4, np.nan) for t in transformed],
        dtype=np.float64,
    )
    fpos = pos_arr[idx]  # (F, 3, 4) clip positions per face corner
    x, y, z, w = fpos[..., 0], fpos[..., 1], fpos[..., 2], fpos[..., 3]
    # Distances to the six homogeneous planes plus the positive-w safety plane,
    # same formulas as _distance, evaluated for every face at once.
    dist = np.stack([w + x, w - x, w + y, w - y, w + z, w - z, w - _MIN_W], axis=-1)
    fully_inside = face_ok & (dist >= 0.0).all(axis=(1, 2))

    # Perspective divide + screen mapping for the (common) unclipped faces;
    # identical elementwise float64 math to the per-vertex slow path.
    inv_w = 1.0 / w
    ndc = fpos[..., :3] * inv_w[..., None]
    sx = (ndc[..., 0] + 1.0) * 0.5 * width
    sy = (1.0 - ndc[..., 1]) * 0.5 * height
    screen = np.stack([sx, sy, ndc[..., 2]], axis=-1).astype(np.float32)
    finite = np.isfinite(screen).all(axis=(1, 2))
    # Signed area with the exact operand order of edge_function(s0, s1, s2):
    # (s2x - s0x) * (s1y - s0y) - (s2y - s0y) * (s1x - s0x), all float32.
    area = ((screen[:, 2, 0] - screen[:, 0, 0]) * (screen[:, 1, 1] - screen[:, 0, 1])
            - (screen[:, 2, 1] - screen[:, 0, 1]) * (screen[:, 1, 0] - screen[:, 0, 0]))
    emit_fast = fully_inside & finite & np.isfinite(area) & (area > np.float32(1e-9))

    slots = [None] * len(idx)
    for fi in range(len(idx)):
        if not face_ok[fi]:
            continue  # discarded vertex -> primitive fails closed
        if emit_fast[fi]:
            s = screen[fi]
            i0, i1, i2 = idx[fi]
            slots[fi] = [(
                s[0], s[1], s[2],
                float(inv_w[fi, 0]), float(inv_w[fi, 1]), float(inv_w[fi, 2]),
                transformed[i0][1], transformed[i1][1], transformed[i2][1],
                float(area[fi]),
            )]
            continue
        # Clipping slow path: unchanged Sutherland–Hodgman semantics.
        triangle = [transformed[i] for i in idx[fi]]
        out = []
        for clipped in clip_triangle(triangle):
            screen_v = []
            inverse_w = []
            for position, _ in clipped:
                wv = float(position[3])
                if wv < _MIN_W:
                    break
                inv = 1.0 / wv
                ndc_v = position[:3] * inv
                s = np.array([
                    (ndc_v[0] + 1.0) * 0.5 * width,
                    (1.0 - ndc_v[1]) * 0.5 * height,
                    ndc_v[2],
                ], dtype=np.float32)
                if not np.isfinite(s).all():
                    break
                screen_v.append(s)
                inverse_w.append(inv)
            if len(screen_v) != 3:
                continue
            area_v = float(edge_function(screen_v[0], screen_v[1], screen_v[2]))
            if not np.isfinite(area_v) or area_v <= 1e-9:
                continue
            out.append((
                screen_v[0], screen_v[1], screen_v[2],
                inverse_w[0], inverse_w[1], inverse_w[2],
                clipped[0][1], clipped[1][1], clipped[2][1], area_v,
            ))
        slots[fi] = out
    return [tri for slot in slots if slot for tri in slot]
