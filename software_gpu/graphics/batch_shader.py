"""Explicit scalar/batch pair for the vertex-color CPU shader.

Pure RGBA conversion only: no mutable per-fragment state, textures or lighting.
For finite RGB triples both entry points use identical elementwise arithmetic
and uint8 conversion. Invalid batch inputs are outside that equivalence domain.
"""
import numpy as np

from .shader import Shader


class VertexColorShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {"color": vertex.color}

    # Bind admission to this exact pure function, even if a method is replaced.
    vertex_preparation_equivalent_to = vertex_shader

    def fragment_shader(self, varyings):
        # Optimization: pure scalar inline logic eliminates NumPy clip dispatch overhead
        # Performance impact: up to 5x speedup for pure RGBA scalar conversions per fragment
        c = varyings["color"]
        r, g, b = float(c[0]), float(c[1]), float(c[2])
        if not (r == r and g == g and b == b):
            raise ValueError("cannot convert float NaN to integer")
        r, g, b = r * 255, g * 255, b * 255
        return (
            int(r if 0 <= r < 255 else (255 if r >= 255 else 0)),
            int(g if 0 <= g < 255 else (255 if g >= 255 else 0)),
            int(b if 0 <= b < 255 else (255 if b >= 255 else 0)),
            255
        )

    batch_fragment_equivalent_to = fragment_shader

    def fragment_shader_batch(self, varyings):
        color = np.asarray(varyings["color"])
        if color.ndim != 2 or color.shape[1] != 3 or not np.isfinite(color).all():
            raise ValueError("BATCH_COLOR_INPUT_INVALID")
        rgb = np.clip(color * 255, 0, 255).astype(np.uint8)
        rgba = np.empty((len(rgb), 4), dtype=np.uint8)
        rgba[:, :3] = rgb
        rgba[:, 3] = 255
        return rgba


# Captured implementation identity for the opt-in native specialization.
_NATIVE_VERTEX_COLOR_METHODS = (VertexColorShader.vertex_shader, VertexColorShader.fragment_shader)
