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
        color = varyings["color"]
        # The real vertex stage provides a fixed float32 triple. Preserve
        # NumPy scalar multiplication (including float32 rounding) and avoid
        # three temporary arrays and dispatch into np.clip/astype per pixel.
        # Other dtypes, shapes and NaN retain the original NumPy conversion.
        if (isinstance(color, np.ndarray) and color.shape == (3,)
                and color.dtype in (np.dtype("float32"), np.dtype("float64"))):
            r = color[0] * 255
            g = color[1] * 255
            b = color[2] * 255
            if r == r and g == g and b == b:
                return (
                    0 if r <= 0 else 255 if r >= 255 else int(r),
                    0 if g <= 0 else 255 if g >= 255 else int(g),
                    0 if b <= 0 else 255 if b >= 255 else int(b),
                    255
                )
        rgb = np.clip(np.asarray(color) * 255, 0, 255).astype(np.uint8)
        return int(rgb[0]), int(rgb[1]), int(rgb[2]), 255

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
