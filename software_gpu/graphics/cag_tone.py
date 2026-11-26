"""Opt-in RGB8 smoothstep shader. Network and credentials stay outside rendering."""
import numpy as np

from .batch_shader import VertexColorShader


def tone(i):
    return i * i * (765 - 2 * i) // 65025


class CagToneShader(VertexColorShader):
    """Scalar integer reference and equivalent precomputed RGB transfer function."""
    def __init__(self, table):
        if type(table) is not bytes or table != bytes(map(tone, range(256))):
            raise ValueError("Invalid smoothstep table")
        self._table = np.frombuffer(table, dtype=np.uint8)

    def fragment_shader(self, varyings):
        r, g, b, a = super().fragment_shader(varyings)
        return tone(r), tone(g), tone(b), a

    batch_fragment_equivalent_to = fragment_shader

    def fragment_shader_batch(self, varyings):
        rgba = super().fragment_shader_batch(varyings)
        rgba[:, :3] = self._table[rgba[:, :3]]
        return rgba


_CAG_METHODS = (CagToneShader.fragment_shader, CagToneShader.fragment_shader_batch)
