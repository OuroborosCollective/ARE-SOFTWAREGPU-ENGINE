#!/usr/bin/env python3
"""Offline owner-asset GLB normal repair for AREMDL03 PBR admission.

This utility does not simplify geometry. It only appends an area-weighted
NORMAL accessor for an otherwise static, indexed, UV-textured glTF2 mesh.
It requires the exact source SHA-256 and never touches the source file.
Original indices, positions, UVs, embedded image bytes, and material JSON
remain byte-for-byte unchanged within the existing BIN and accessor views.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile

import numpy as np

MAX_GLB_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_VERTICES = 6_100_000
MAX_TRIANGLES = 8_000_000
SUPPORTED_INDICES = {5121: '<u1', 5123: '<u2', 5125: '<u4'}


class NativeLodError(ValueError):
    """A fail-closed asset admission failure (no source payload in errors)."""


def need(test, code):
    if not test:
        raise NativeLodError(code)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'NATIVE_LOD_DUPLICATE_JSON')
        result[key] = value
    return result


def _read_glb(raw):
    need(isinstance(raw, bytes) and 32 <= len(raw) <= MAX_GLB_BYTES,
         'NATIVE_LOD_GLB_BYTES')
    magic, version, total = struct.unpack_from('<4sII', raw)
    need((magic, version, total) == (b'glTF', 2, len(raw)), 'NATIVE_LOD_GLB_HEADER')
    jsonlen, jsonkind = struct.unpack_from('<I4s', raw, 12)
    need(jsonkind == b'JSON' and 4 <= jsonlen <= MAX_JSON_BYTES
         and jsonlen % 4 == 0 and 20 + jsonlen + 8 <= len(raw), 'NATIVE_LOD_JSON_CHUNK')
    binlen, binkind = struct.unpack_from('<I4s', raw, 20 + jsonlen)
    need(binkind == b'BIN\0' and binlen % 4 == 0
         and 28 + jsonlen + binlen == len(raw), 'NATIVE_LOD_BINARY_CHUNK')
    try:
        doc = json.loads(raw[20:20 + jsonlen].decode('utf-8'),
                         object_pairs_hook=_unique_object,
                         parse_constant=lambda _: need(False, 'NATIVE_LOD_NONFINITE_JSON'))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise NativeLodError('NATIVE_LOD_INVALID_JSON') from exc
    need(isinstance(doc, dict) and doc.get('asset', {}).get('version') == '2.0'
         and not doc.get('extensionsRequired'), 'NATIVE_LOD_GLTF_VERSION')
    buffers = doc.get('buffers', [])
    need(isinstance(buffers, list) and len(buffers) == 1
         and isinstance(buffers[0], dict) and 'uri' not in buffers[0]
         and type(buffers[0].get('byteLength')) is int,
         'NATIVE_LOD_BUFFER_SUBSET')
    payload_length = buffers[0]['byteLength']
    need(0 < payload_length <= binlen and binlen - payload_length <= 3,
         'NATIVE_LOD_BUFFER_LENGTH')
    payload = raw[28 + jsonlen:28 + jsonlen + payload_length]
    return doc, payload


def _attribute(doc, payload, index, kind, components, count=None):
    accessors = doc.get('accessors', [])
    views = doc.get('bufferViews', [])
    need(type(index) is int and 0 <= index < len(accessors), 'NATIVE_LOD_ACCESSOR_INDEX')
    spec = accessors[index]
    need(isinstance(spec, dict) and spec.get('type') == kind
         and spec.get('componentType') in components
         and 'sparse' not in spec and not spec.get('normalized', False),
         'NATIVE_LOD_ACCESSOR_FORMAT')
    n = spec.get('count')
    need(type(n) is int and 1 <= n <= max(MAX_VERTICES, MAX_TRIANGLES * 3)
         and (count is None or n == count), 'NATIVE_LOD_ACCESSOR_COUNT')
    vindex = spec.get('bufferView')
    need(type(vindex) is int and 0 <= vindex < len(views), 'NATIVE_LOD_BUFFER_VIEW')
    view = views[vindex]
    need(isinstance(view, dict) and view.get('buffer', 0) == 0,
         'NATIVE_LOD_VIEW_BUFFER')
    dtype = np.dtype(components[spec['componentType']])
    byte_stride = dtype.itemsize * {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3}[kind]
    stride = view.get('byteStride', byte_stride)
    view_offset = view.get('byteOffset', 0)
    offset = spec.get('byteOffset', 0)
    length = view.get('byteLength')
    need(all(type(x) is int for x in (stride, view_offset, offset, length))
         and stride >= byte_stride and stride <= 256 and stride % dtype.itemsize == 0
         and view_offset >= 0 and offset >= 0 and length >= byte_stride
         and (view_offset + offset) % dtype.itemsize == 0
         and offset + (n - 1) * stride + byte_stride <= length
         and view_offset + length <= len(payload), 'NATIVE_LOD_ACCESSOR_BOUNDS')
    dims = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3}[kind]
    return np.ndarray((n, dims), dtype=dtype, buffer=payload,
                      offset=view_offset + offset,
                      strides=(stride, dtype.itemsize)).copy()


def inspect_lod(raw, *, pbr=True, include_parts=False):
    """Static source-parsed compatibility check, not a native runtime proof."""
    doc, payload = _read_glb(raw)
    meshes, nodes = doc.get('meshes', []), doc.get('nodes', [])
    need(isinstance(meshes, list) and len(meshes) == 1
         and isinstance(meshes[0], dict) and len(meshes[0].get('primitives', [])) == 1
         and isinstance(nodes, list) and 1 <= len(nodes) <= 256,
         'NATIVE_LOD_MESH_SUBSET')
    prim = meshes[0]['primitives'][0]
    need(isinstance(prim, dict) and prim.get('mode', 4) == 4
         and not prim.get('targets') and not prim.get('extensions')
         and not doc.get('skins') and not doc.get('animations'),
         'NATIVE_LOD_STATIC_TRIANGLES')
    instances = [i for i, n in enumerate(nodes) if isinstance(n, dict) and 'mesh' in n]
    need(len(instances) == 1 and nodes[instances[0]]['mesh'] == 0
         and 'skin' not in nodes[instances[0]], 'NATIVE_LOD_SINGLE_INSTANCE')
    attrs = prim.get('attributes', {})
    need(isinstance(attrs, dict) and 'POSITION' in attrs
         and 'TEXCOORD_0' in attrs and 'TANGENT' not in attrs,
         'NATIVE_LOD_UV_POSITION')
    positions = _attribute(doc, payload, attrs['POSITION'], 'VEC3', {5126: '<f4'})
    nverts = len(positions)
    need(nverts <= MAX_VERTICES and np.isfinite(positions).all()
         and (np.abs(positions) < 1e12).all(), 'NATIVE_LOD_POSITIONS')
    uvs = _attribute(doc, payload, attrs['TEXCOORD_0'], 'VEC2', {5126: '<f4'}, count=nverts)
    need(np.isfinite(uvs).all() and (np.abs(uvs) <= 1e6).all(), 'NATIVE_LOD_UV')
    flat = _attribute(doc, payload, prim.get('indices'), 'SCALAR', SUPPORTED_INDICES)
    need(len(flat) % 3 == 0 and len(flat) // 3 <= MAX_TRIANGLES
         and int(flat.max()) < nverts, 'NATIVE_LOD_TRIANGLE_INDEX')
    faces = np.asarray(flat.reshape(-1, 3), dtype=np.uint32)
    materials = doc.get('materials', [])
    matindex = prim.get('material')
    need(isinstance(materials, list) and type(matindex) is int
         and 0 <= matindex < len(materials), 'NATIVE_LOD_MATERIAL')
    material = materials[matindex]
    need(isinstance(material, dict) and not material.get('extensions')
         and material.get('alphaMode', 'OPAQUE') == 'OPAQUE'
         and type(material.get('doubleSided', False)) is bool,
         'NATIVE_LOD_MATERIAL_SUBSET')
    for image in doc.get('images', []):
        need(isinstance(image, dict) and 'uri' not in image
             and type(image.get('bufferView')) is int,
             'NATIVE_LOD_EXTERNAL_IMAGE')
    normal_index = attrs.get('NORMAL')
    if pbr:
        need(normal_index is not None, 'NATIVE_LOD_MISSING_NORMAL')
    if normal_index is not None:
        normals = _attribute(doc, payload, normal_index, 'VEC3', {5126: '<f4'}, count=nverts)
        lengths = np.linalg.norm(normals.astype(np.float64), axis=1)
        need(np.isfinite(normals).all() and (np.abs(normals) <= 1.001).all()
             and (lengths > 1e-10).all(), 'NATIVE_LOD_INVALID_NORMAL')
    result = dict(vertices=nverts, triangles=len(faces), images=doc.get('images', []),
                  materials=materials, normal_present=normal_index is not None)
    if include_parts:
        result.update(doc=doc, bin_payload=payload, positions=positions,
                      uvs=uvs, faces=faces)
    return result


def repair_lod(raw, expected_sha256):
    """Return new GLB bytes + immutable identity receipt; source is never mutated."""
    need(isinstance(expected_sha256, str) and bool(re.fullmatch(r'[0-9a-f]{64}', expected_sha256))
         and hashlib.sha256(raw).hexdigest() == expected_sha256,
         'NATIVE_LOD_SOURCE_SHA')
    info = inspect_lod(raw, pbr=False, include_parts=True)
    need(not info['normal_present'], 'NATIVE_LOD_NORMALS_ALREADY_PRESENT')
    pos, faces = info['positions'].astype('<f8'), info['faces']
    p0, p1, p2 = pos[faces[:, 0]], pos[faces[:, 1]], pos[faces[:, 2]]
    weighted = np.cross(p1 - p0, p2 - p0)
    need(np.isfinite(weighted).all()
         and (np.linalg.norm(weighted, axis=1) > 1e-14).all(),
         'NATIVE_LOD_DEGENERATE_TRIANGLES')
    normals = np.zeros_like(pos)
    for component in range(3):
        np.add.at(normals, faces[:, component], weighted)
    lengths = np.linalg.norm(normals, axis=1)
    need(np.isfinite(normals).all() and (lengths > 1e-10).all(),
         'NATIVE_LOD_UNDEFINED_NORMAL')
    unit = np.ascontiguousarray(normals / lengths[:, None], dtype='<f4')

    doc = info['doc']
    payload = info['bin_payload']
    # All original offsets remain unchanged. A new aligned view/accessor is
    # appended after the *declared* original binary byteLength.
    padding = b'\0' * (-len(payload) % 4)
    binary = payload + padding + unit.tobytes()
    view_index = len(doc.get('bufferViews', []))
    doc['bufferViews'].append(dict(buffer=0, byteOffset=len(payload) + len(padding),
                                   byteLength=unit.nbytes))
    accessor_index = len(doc.get('accessors', []))
    doc['accessors'].append(dict(bufferView=view_index, componentType=5126,
                                 count=len(unit), type='VEC3'))
    doc['meshes'][0]['primitives'][0]['attributes']['NORMAL'] = accessor_index
    doc['buffers'][0]['byteLength'] = len(binary)
    json_bytes = json.dumps(doc, ensure_ascii=True, allow_nan=False,
                            sort_keys=True, separators=(',', ':')).encode('utf-8')
    json_bytes += b' ' * (-len(json_bytes) % 4)
    need(len(json_bytes) <= MAX_JSON_BYTES, 'NATIVE_LOD_JSON_BUDGET')
    binary += b'\0' * (-len(binary) % 4)
    total = 28 + len(json_bytes) + len(binary)
    need(total <= MAX_GLB_BYTES, 'NATIVE_LOD_OUTPUT_BUDGET')
    fixed = b''.join((struct.pack('<4sII', b'glTF', 2, total),
                      struct.pack('<I4s', len(json_bytes), b'JSON'), json_bytes,
                      struct.pack('<I4s', len(binary), b'BIN\0'), binary))
    verify = inspect_lod(fixed, pbr=True)
    need(verify['vertices'] == info['vertices']
         and verify['triangles'] == info['triangles'], 'NATIVE_LOD_REPAIR_DRIFT')
    return fixed, dict(protocol='are.owner-lod-native-normals.v1',
                       operation='generated-area-weighted-normals',
                       before_sha256=expected_sha256,
                       after_sha256=hashlib.sha256(fixed).hexdigest(),
                       before_bytes=len(raw), after_bytes=len(fixed),
                       vertices=verify['vertices'], triangles=verify['triangles'],
                       original_binary_prefix_preserved=True,
                       textures_materials_untouched=True,
                       native_runtime_executed=False)


def convert_file(source, target, expected_sha256):
    source, target = Path(source), Path(target)
    need(source.is_file() and not source.is_symlink() and source.resolve() != target.resolve()
         and not target.exists(), 'NATIVE_LOD_SAFE_PATHS')
    need(32 <= source.stat().st_size <= MAX_GLB_BYTES, 'NATIVE_LOD_FILE_SIZE')
    fixed, receipt = repair_lod(source.read_bytes(), expected_sha256)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.native-lod-',
                                         suffix='.tmp', delete=False) as f:
            temp_path = Path(f.name)
            f.write(fixed)
            f.flush()
            os.fsync(f.fileno())
        need(not target.exists(), 'NATIVE_LOD_TARGET_EXISTS')
        temp_path.replace(target)
        need(hashlib.sha256(target.read_bytes()).hexdigest() == receipt['after_sha256'],
             'NATIVE_LOD_OUTPUT_READBACK')
        return receipt
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args(argv)
    try:
        result = convert_file(args.input, args.output, args.expected_sha256)
        if args.receipt:
            need(args.receipt.resolve() not in (args.input.resolve(), args.output.resolve())
                 and not args.receipt.exists(), 'NATIVE_LOD_RECEIPT_PATH')
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, sort_keys=True))
        return 0
    except (NativeLodError, OSError, UnicodeError, ValueError) as exc:
        print(f'NATIVE_LOD_BLOCKED:{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
