"""Read-only, bounded FPLBase FMSH/FMAT dependency preflight for offline CPU tools.

This checks a *subset* of the FlatBuffers wire schema: mesh surfaces, index
vector extents, material references and texture filenames. It deliberately
never loads external code or routes FPLBase/OpenGL rendering into ARE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import sys

PROTOCOL = 'are.fplbase-preflight.v1'
UPSTREAM_SHA = '4c9f5b751427f3be56a9277497b9078079aa1b9c'
MAX_MESH_BYTES = 128 * 1024 * 1024
MAX_MATERIAL_BYTES = 2 * 1024 * 1024
MAX_TEXTURE_BYTES = 64 * 1024 * 1024
MAX_ASSET_BYTES = 512 * 1024 * 1024
TEXTURE_EXTENSIONS = frozenset(('.png', '.jpg', '.jpeg', '.webp', '.tga', '.ktx', '.pvr', '.pkm'))


class PreflightError(ValueError):
    """Stable fail-closed code for invalid source data."""


def _need(ok: bool, code: str) -> None:
    if not ok:
        raise PreflightError(code)


def _value(raw: bytes, offset: int, fmt: str, code: str = 'FPLBASE_OFFSET_INVALID') -> int:
    n = struct.calcsize('<' + fmt)
    _need(0 <= offset <= len(raw) - n, code)
    return struct.unpack_from('<' + fmt, raw, offset)[0]


def _safe_path(root: Path, name: str) -> Path:
    _need(isinstance(name, str) and 1 <= len(name) <= 255
          and not any(ch in name for ch in ('\\', ':', '\x00')),
          'FPLBASE_PATH_INVALID')
    rel = PurePosixPath(name)
    _need(not rel.is_absolute() and all(p not in ('.', '..') for p in name.split('/'))
          and all(p for p in name.split('/')), 'FPLBASE_PATH_INVALID')
    target = root
    for part in rel.parts:
        target = target / part
        _need(not target.is_symlink(), 'FPLBASE_PATH_INVALID')
    try:
        canonical = target.resolve(strict=True)
    except (OSError, RuntimeError):
        raise PreflightError('FPLBASE_FILE_MISSING') from None
    _need(canonical.is_relative_to(root) and canonical.is_file(), 'FPLBASE_PATH_INVALID')
    return canonical


def _load(root: Path, name: str, limit: int, extension: str) -> tuple[bytes, dict]:
    _need(name.lower().endswith(extension), 'FPLBASE_EXTENSION_INVALID')
    path = _safe_path(root, name)
    size = path.stat().st_size
    _need(8 <= size <= limit, 'FPLBASE_FILE_SIZE_INVALID')
    # Input is hashed in exactly the bytes that were parsed, not using timestamps.
    raw = path.read_bytes()
    _need(len(raw) == size, 'FPLBASE_FILE_CHANGED')
    return raw, {'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def _root_table(raw: bytes, identifier: bytes) -> int:
    _need(len(raw) >= 12, 'FPLBASE_ROOT_INVALID')
    _need(raw[4:8] == identifier, 'FPLBASE_IDENTIFIER_INVALID')
    root = _value(raw, 0, 'I', 'FPLBASE_ROOT_INVALID')
    _need(8 <= root <= len(raw) - 4, 'FPLBASE_ROOT_INVALID')
    _vtable(raw, root)
    return root


def _vtable(raw: bytes, table: int) -> tuple[int, int, int]:
    rel = _value(raw, table, 'i')
    vt = table - rel
    _need(rel != 0 and 8 <= vt <= len(raw) - 4, 'FPLBASE_VTABLE_INVALID')
    size = _value(raw, vt, 'H')
    objsize = _value(raw, vt + 2, 'H')
    _need(4 <= size <= 128 and not size % 2 and vt + size <= len(raw)
          and 4 <= objsize and table + objsize <= len(raw), 'FPLBASE_VTABLE_INVALID')
    return vt, size, objsize


def _field(raw: bytes, table: int, index: int, scalar_size: int = 4) -> int | None:
    vt, length, objlen = _vtable(raw, table)
    slot = vt + 4 + 2 * index
    if slot + 2 > vt + length:
        return None
    offset = _value(raw, slot, 'H')
    if offset == 0:
        return None
    _need(offset >= 4 and offset + scalar_size <= objlen, 'FPLBASE_FIELD_INVALID')
    return table + offset


def _offset(raw: bytes, position: int | None) -> int | None:
    if position is None:
        return None
    jump = _value(raw, position, 'I')
    target = position + jump
    _need(jump >= 4 and target < len(raw), 'FPLBASE_OFFSET_INVALID')
    return target


def _vector(raw: bytes, start: int | None, item_size: int, max_items: int,
            required: bool = False) -> tuple[int, int]:
    _need(start is not None or not required, 'FPLBASE_REQUIRED_FIELD')
    if start is None:
        return 0, 0
    count = _value(raw, start, 'I')
    _need(count <= max_items and (not required or count > 0), 'FPLBASE_VECTOR_COUNT_INVALID')
    first = start + 4
    _need(first + count * item_size <= len(raw), 'FPLBASE_VECTOR_BOUNDS_INVALID')
    return first, count


def _string(raw: bytes, position: int | None) -> str:
    start = _offset(raw, position)
    _need(start is not None, 'FPLBASE_REQUIRED_FIELD')
    n = _value(raw, start, 'I')
    _need(1 <= n <= 255 and start + 4 + n < len(raw), 'FPLBASE_STRING_BOUNDS_INVALID')
    _need(raw[start + 4 + n] == 0, 'FPLBASE_STRING_TERMINATOR_INVALID')
    try:
        return raw[start+4:start+4+n].decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        raise PreflightError('FPLBASE_STRING_ENCODING_INVALID') from None


def _refs(raw: bytes, table: int, field_number: int, limit: int) -> list[int]:
    first, count = _vector(raw, _offset(raw, _field(raw, table, field_number)), 4, limit)
    return [first + i * 4 for i in range(count)]


def _mesh_materials(raw: bytes) -> list[str]:
    root = _root_table(raw, b'FMSH')
    version_at = _field(raw, root, 15, 2)
    version = 0 if version_at is None else _value(raw, version_at, 'H')
    _need(version in (0, 1), 'FPLBASE_MESH_VERSION_UNSUPPORTED')
    first, count = _vector(raw, _offset(raw, _field(raw, root, 0)), 4, 1024, True)
    materials = []
    for i in range(count):
        surface = _offset(raw, first + i * 4)
        _need(surface is not None, 'FPLBASE_REQUIRED_FIELD')
        _vtable(raw, surface)
        index16 = _offset(raw, _field(raw, surface, 0))
        index32 = _offset(raw, _field(raw, surface, 2))
        _need((index16 is None) != (index32 is None), 'FPLBASE_MESH_INDEX_FORMAT_INVALID')
        _, indices = _vector(raw, index16 if index16 is not None else index32,
                             2 if index16 is not None else 4, 8_000_000, True)
        _need(indices % 3 == 0, 'FPLBASE_MESH_TRIANGLES_INVALID')
        materials.append(_string(raw, _field(raw, surface, 1)))
    return sorted(set(materials))


def _material_textures(raw: bytes) -> list[str]:
    root = _root_table(raw, b'FMAT')
    return sorted(set(_string(raw, position) for position in _refs(raw, root, 0, 128)))


def inspect_asset(root_dir: str | Path, mesh: str) -> dict:
    """Produce a deterministic, read-only dependency manifest for an FMSH asset.

    This is not a complete FlatBuffers schema validator, mesh converter or renderer.
    Only the bounded dependency portion of FPLBase's schema is inspected.
    """
    root = Path(root_dir).resolve(strict=True)
    _need(root.is_dir(), 'FPLBASE_ROOT_DIR_INVALID')
    raw, mesh_rec = _load(root, mesh, MAX_MESH_BYTES, '.fplmesh')
    mats = []
    total_bytes = len(raw)
    texture_names = set()
    for name in _mesh_materials(raw):
        material_bytes, record = _load(root, name, MAX_MATERIAL_BYTES, '.fplmat')
        total_bytes += len(material_bytes)
        _need(total_bytes <= MAX_ASSET_BYTES, 'FPLBASE_ASSET_SIZE_INVALID')
        texture_names.update(_material_textures(material_bytes))
        mats.append(record)
    textures = []
    for name in sorted(texture_names):
        suffix = Path(name).suffix.lower()
        _need(suffix in TEXTURE_EXTENSIONS, 'FPLBASE_TEXTURE_EXTENSION_INVALID')
        _, rec = _load(root, name, MAX_TEXTURE_BYTES, suffix)
        total_bytes += rec['bytes']
        _need(total_bytes <= MAX_ASSET_BYTES, 'FPLBASE_ASSET_SIZE_INVALID')
        textures.append(rec)
    return {'protocol': PROTOCOL, 'authority': 'offline-derived',
            'schema_reference': f'google/fplbase@{UPSTREAM_SHA}',
            'validation_scope': 'bounded FMSH/FMAT dependency references; not full mesh validation',
            'mesh': mesh_rec, 'materials': mats, 'textures': textures,
            'total_source_bytes': total_bytes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, help='Trusted FPLBase asset base directory')
    parser.add_argument('--mesh', required=True, help='Relative .fplmesh under --root')
    parser.add_argument('--output', default='-', help='JSON path or - for stdout')
    args = parser.parse_args(argv)
    try:
        manifest = inspect_asset(args.root, args.mesh)
    except (PreflightError, OSError) as exc:
        print(f'FPLBASE_PREFLIGHT_REJECTED:{exc}', file=sys.stderr)
        return 2
    encoded = json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n'
    if args.output == '-':
        print(encoded, end='')
    else:
        Path(args.output).write_text(encoded, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
