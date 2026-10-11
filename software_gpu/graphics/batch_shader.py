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

    def fragment_shader(self, varyings):
        rgb = np.clip(np.asarray(varyings["color"]) * 255, 0, 255).astype(np.uint8)
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
