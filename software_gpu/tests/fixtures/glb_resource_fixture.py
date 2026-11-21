"""Deterministically generated *valid* glTF 2.0 GLB test geometry.

These are synthetic stress fixtures, not Owner assets, native-model admission,
or independent upstream GLBs. Input bytes are actually parsed and SHA-pinned.
"""
from __future__ import annotations

import json
import struct


def make_resource_glb(mesh_count: int, *, bin_bytes: int = 256,
                      materials: int = 4, accessor_variants: int = 4) -> bytes:
    if (type(mesh_count) is not int or mesh_count not in (1, 100, 1300, 3500)
            or type(bin_bytes) is not int or bin_bytes < 44 or bin_bytes % 4
            or type(materials) is not int or not 1 <= materials <= 8
            or type(accessor_variants) is not int or not 1 <= accessor_variants <= 8):
        raise ValueError("GLB_RESOURCE_FIXTURE_INVALID")
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": 36},
        {"buffer": 0, "byteOffset": 36, "byteLength": 6},
    ]
    accessors = []
    for _ in range(accessor_variants):
        accessors.extend([
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ])
    meshes = [
        {"primitives": [{
            "attributes": {"POSITION": 2 * (i % accessor_variants)},
            "indices": 2 * (i % accessor_variants) + 1,
            "material": i % materials,
            "mode": 4,
        }]}
        for i in range(mesh_count)
    ]
    doc = {
        "asset": {"version": "2.0", "generator": "ARE deterministic GLB resource fixture"},
        "buffers": [{"byteLength": bin_bytes}],
        "bufferViews": views,
        "accessors": accessors,
        "materials": [{"doubleSided": True} for _ in range(materials)],
        "meshes": meshes,
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    header = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8")
    header += b" " * (-len(header) % 4)
    binary = struct.pack("<9f3H", -.3, -.3, 0., .3, -.3, 0., 0., .3, 0., 0, 1, 2)
    binary += b"\x00" * (bin_bytes - len(binary))
    chunks = (struct.pack("<II", len(header), 0x4E4F534A) + header
              + struct.pack("<II", len(binary), 0x004E4942) + binary)
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks
