"""Bounded, read-only GLB topology and material diagnostic evidence.

Inspired by the *diagnostic evidence* design of arXiv:2611.04102 (preprint).
This is NOT that paper's trained classifier, full glTF validation or a renderer.
No quality labels, PSNR, images, or native runtime claims are generated here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
from collections import Counter, defaultdict

from tools.glb_container_preflight import inspect_glb

PROTOCOL = "are.glb-diagnostic-evidence.v1"
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_TRIANGLES = 200_000
MAX_JSON_BYTES = 8 * 1024 * 1024
_COMPONENT = {5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError("GLB_DIAGNOSTIC_" + code)


def _array(doc: dict, name: str) -> list:
    value = doc.get(name, [])
    _need(isinstance(value, list), "SCHEMA_INVALID")
    return value


def _ref(items: list, index: int, code: str) -> dict:
    _need(type(index) is int and 0 <= index < len(items), code)
    value = items[index]
    _need(isinstance(value, dict), code)
    return value


def _embedded_accessor(doc: dict, binary: bytes, index: int, components: int,
                       types: tuple[int, ...], budget: int) -> list[tuple] | None:
    """Read bounded, uncompressed embedded bufferViews; unsupported layouts are unknown."""
    accessor = _ref(_array(doc, "accessors"), index, "ACCESSOR_REF_INVALID")
    _need(type(accessor.get("count")) is int and accessor["count"] >= 0,
          "ACCESSOR_COUNT_INVALID")
    count = accessor["count"]
    if count > budget:
        return None
    _need(accessor.get("type") in _COMPONENTS, "ACCESSOR_TYPE_INVALID")
    if _COMPONENTS[accessor["type"]] != components:
        return None
    ctype = accessor.get("componentType")
    if ctype not in types or ctype not in _COMPONENT:
        return None
    if "sparse" in accessor or "bufferView" not in accessor or accessor.get("normalized"):
        return None
    view = _ref(_array(doc, "bufferViews"), accessor["bufferView"],
                "BUFFERVIEW_REF_INVALID")
    if "extensions" in view or view.get("buffer") != 0:
        return None
    _, width = _COMPONENT[ctype]
    fmt = "<" + _COMPONENT[ctype][0] * components
    element_bytes = width * components
    stride = view.get("byteStride", element_bytes)
    offset = view.get("byteOffset", 0)
    local = accessor.get("byteOffset", 0)
    view_length = view.get("byteLength")
    _need(all(type(x) is int and x >= 0 for x in (stride, offset, local, view_length)),
          "BUFFERVIEW_BOUNDS_INVALID")
    _need(stride >= element_bytes and stride % width == 0, "BUFFERVIEW_STRIDE_INVALID")
    _need(offset % width == 0 and local % width == 0, "ACCESSOR_ALIGNMENT_INVALID")
    used = 0 if not count else (count - 1) * stride + element_bytes
    _need(local + used <= view_length, "ACCESSOR_BOUNDS_INVALID")
    _need(offset + view_length <= len(binary), "BUFFERVIEW_BOUNDS_INVALID")
    start = offset + local
    return [struct.unpack_from(fmt, binary, start + i * stride) for i in range(count)]


def _topology(positions: list[tuple], faces: list[tuple[int, int, int]]) -> dict:
    """Count index-topology components. Spatially coincident vertices remain distinct."""
    used = set()
    edges = Counter()
    parent = {}

    def root(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(a: int, b: int) -> None:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    zero = 0
    for a, b, c in faces:
        for idx in (a, b, c):
            used.add(idx)
            parent.setdefault(idx, idx)
        for i, j in ((a, b), (b, c), (c, a)):
            if i != j:
                edge = (min(i, j), max(i, j))
                edges[edge] += 1
                union(i, j)
        pa, pb, pc = positions[a], positions[b], positions[c]
        ax, ay, az = (pb[0]-pa[0], pb[1]-pa[1], pb[2]-pa[2])
        bx, by, bz = (pc[0]-pa[0], pc[1]-pa[1], pc[2]-pa[2])
        cross = (ay*bz-az*by, az*bx-ax*bz, ax*by-ay*bx)
        if all(v == 0.0 for v in cross):
            zero += 1
    components = len({root(i) for i in used})
    return {
        "status": "analyzed", "triangles": len(faces),
        "used_vertices": len(used), "unique_edges": len(edges),
        "boundary_edges": sum(v == 1 for v in edges.values()),
        "nonmanifold_edges": sum(v > 2 for v in edges.values()),
        "connected_components": components,
        "zero_area_triangles": zero,
        "euler_characteristic": len(used) - len(edges) + len(faces),
    }


def _material(doc: dict, primitive: dict) -> dict:
    if "material" not in primitive:
        return {"status": "no_material_reference"}
    material = _ref(_array(doc, "materials"), primitive["material"],
                    "MATERIAL_REF_INVALID")
    pbr = material.get("pbrMetallicRoughness", {})
    _need(isinstance(pbr, dict), "MATERIAL_INVALID")
    refs = []
    for slot in ("baseColorTexture", "metallicRoughnessTexture"):
        if slot in pbr:
            refs.append(pbr[slot])
    for slot in ("normalTexture", "occlusionTexture", "emissiveTexture"):
        if slot in material:
            refs.append(material[slot])
    if not refs:
        return {"status": "material_without_image_texture"}
    textures = _array(doc, "textures")
    images = _array(doc, "images")
    states = []
    for ref in refs:
        _need(isinstance(ref, dict), "TEXTURE_REF_INVALID")
        texture = _ref(textures, ref.get("index"), "TEXTURE_REF_INVALID")
        if "source" not in texture:
            states.append("unresolved")
            continue
        image = _ref(images, texture["source"], "IMAGE_REF_INVALID")
        if "uri" in image:
            uri = image["uri"]
            _need(isinstance(uri, str), "IMAGE_REF_INVALID")
            states.append("embedded_data_uri_not_decoded" if uri.startswith("data:")
                          else "external_unresolved")
        elif "bufferView" in image:
            _ref(_array(doc, "bufferViews"), image["bufferView"],
                 "BUFFERVIEW_REF_INVALID")
            states.append("embedded_image_not_decoded")
        else:
            states.append("unresolved")
    if "external_unresolved" in states:
        return {"status": "external_unresolved", "textures": len(refs)}
    if "unresolved" in states:
        return {"status": "unresolved", "textures": len(refs)}
    return {"status": "textures_referenced_not_rendered", "textures": len(refs)}


def _uv(positions: list[tuple], uv: list[tuple] | None) -> dict:
    if uv is None:
        return {"status": "not_analyzed", "reason": "uv_absent_or_unsupported"}
    _need(len(uv) == len(positions), "UV_COUNT_INVALID")
    by_position = defaultdict(set)
    for p, t in zip(positions, uv):
        _need(all(math.isfinite(x) for x in t), "UV_NONFINITE")
        by_position[tuple(p)].add(tuple(t))
    return {"status": "analyzed",
            "candidate_seam_positions": sum(len(v) > 1 for v in by_position.values()),
            "interpretation": "candidate_only_not_asset_quality_score"}


def inspect_diagnostic_glb(data: bytes, *, max_triangles: int = MAX_TRIANGLES) -> dict:
    """Inspect actual BIN geometry without imports, asset mutation or ML quality claims."""
    _need(type(data) in (bytes, bytearray) and len(data) <= MAX_SOURCE_BYTES,
          "SOURCE_SIZE_INVALID")
    _need(type(max_triangles) is int and 0 <= max_triangles <= MAX_TRIANGLES,
          "BUDGET_INVALID")
    inspect_glb(data)  # Existing independent container framing admission.
    json_len, kind = struct.unpack_from("<II", data, 12)
    _need(kind == 0x4E4F534A and json_len <= MAX_JSON_BYTES, "JSON_SIZE_INVALID")
    doc = json.loads(data[20:20+json_len].decode("utf-8"))
    _need(isinstance(doc, dict), "SCHEMA_INVALID")
    offset = 20 + json_len
    binary = b""
    if offset < len(data):
        bin_length, bin_kind = struct.unpack_from("<II", data, offset)
        _need(bin_kind == 0x004E4942, "BIN_INVALID")
        binary = data[offset+8:offset+8+bin_length]
    records = []
    for mesh_id, mesh in enumerate(_array(doc, "meshes")):
        _need(isinstance(mesh, dict), "MESH_INVALID")
        primitives = mesh.get("primitives", [])
        _need(isinstance(primitives, list), "MESH_INVALID")
        for prim_id, primitive in enumerate(primitives):
            _need(isinstance(primitive, dict), "PRIMITIVE_INVALID")
            material = _material(doc, primitive)
            record = {"mesh": mesh_id, "primitive": prim_id,
                      "material": material,
                      "topology": {"status": "not_analyzed",
                                   "reason": "unsupported_or_unindexed"},
                      "uv": {"status": "not_analyzed",
                             "reason": "uv_absent_or_unsupported"}}
            records.append(record)
            if primitive.get("mode", 4) != 4 or "indices" not in primitive:
                continue
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict) or "POSITION" not in attributes:
                continue
            indices_accessor = _ref(_array(doc, "accessors"), primitive["indices"],
                                    "ACCESSOR_REF_INVALID")
            _need(type(indices_accessor.get("count")) is int and
                  indices_accessor["count"] >= 0, "ACCESSOR_COUNT_INVALID")
            count = indices_accessor["count"]
            _need(count % 3 == 0, "INDEX_COUNT_INVALID")
            if count // 3 > max_triangles:
                record["topology"] = {"status": "not_analyzed", "reason": "analysis_budget"}
                continue
            indices = _embedded_accessor(doc, binary, primitive["indices"], 1,
                                         (5121, 5123, 5125), max_triangles * 3)
            positions = _embedded_accessor(doc, binary, attributes["POSITION"], 3,
                                           (5126,), max(max_triangles * 3, 3))
            if indices is None or positions is None:
                continue
            _need(all(math.isfinite(value) for xyz in positions for value in xyz),
                  "POSITION_NONFINITE")
            faces = []
            for i in range(0, len(indices), 3):
                tri = tuple(entry[0] for entry in indices[i:i+3])
                _need(all(index < len(positions) for index in tri), "INDEX_INVALID")
                faces.append(tri)
            record["topology"] = _topology(positions, faces)
            if "TEXCOORD_0" in attributes:
                uv = _embedded_accessor(doc, binary, attributes["TEXCOORD_0"], 2,
                                        (5126,), max(max_triangles * 3, 3))
                record["uv"] = _uv(positions, uv)
    return {
        "protocol": PROTOCOL, "authority": "offline-derived",
        "source": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        "method_reference": "arxiv:2611.04102v1 (diagnostic separation only)",
        "validation_scope": "indexed embedded float32 position and UV triangle topology; no full glTF validation",
        "rendered_passes": {"beauty": "not_executed", "wireframe": "not_executed",
                            "uv_seam_wireframe": "not_executed"},
        "verdict": "not_assessed", "primitives": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("glb", type=Path)
    parser.add_argument("--max-triangles", type=int, default=MAX_TRIANGLES)
    parser.add_argument("--output", default="-")
    args = parser.parse_args(argv)
    try:
        _need(args.glb.stat().st_size <= MAX_SOURCE_BYTES, "SOURCE_SIZE_INVALID")
        raw = args.glb.read_bytes()
        result = inspect_diagnostic_glb(raw, max_triangles=args.max_triangles)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"GLB_DIAGNOSTIC_REJECTED:{exc}\n")
    output = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output == "-":
        print(output, end="")
    else:
        Path(args.output).write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
