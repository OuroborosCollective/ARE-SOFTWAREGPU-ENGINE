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

    result = []
    for face in indices:
        if len(face) != 3 or any(
            not isinstance(i, (int, np.integer)) or i < 0 or i >= len(transformed)
            for i in face
        ):
            raise IndexError("triangle index outside vertex array")
        triangle = [transformed[i] for i in face]
        if any(point is None for point in triangle):
            continue
        for clipped in clip_triangle(triangle):
            screen = []
            inverse_w = []
            for position, _ in clipped:
                w = float(position[3])
                if w < _MIN_W:
                    break
                inv = 1.0 / w
                ndc = position[:3] * inv
                s = np.array([
                    (ndc[0] + 1.0) * 0.5 * width,
                    (1.0 - ndc[1]) * 0.5 * height,
                    ndc[2],
                ], dtype=np.float32)
                if not np.isfinite(s).all():
                    break
                screen.append(s)
                inverse_w.append(inv)
            if len(screen) != 3:
                continue
            area = float(edge_function(screen[0], screen[1], screen[2]))
            if not np.isfinite(area) or area <= 1e-9:
                continue
            result.append((
                screen[0], screen[1], screen[2],
                inverse_w[0], inverse_w[1], inverse_w[2],
                clipped[0][1], clipped[1][1], clipped[2][1], area,
            ))
    return result
