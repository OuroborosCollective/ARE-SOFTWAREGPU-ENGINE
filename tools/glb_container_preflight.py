"""Strict, dependency-free GLB 2.0 container preflight (not a full glTF validator)."""
from __future__ import annotations

import json
import struct
from pathlib import Path

MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def inspect_glb(data: bytes) -> dict:
    """Reject malformed GLB framing before handing bytes to an asset importer."""
    if len(data) < 20 or data[:4] != MAGIC:
        raise ValueError("invalid GLB header")
    version, total = struct.unpack_from("<II", data, 4)
    if version != 2 or total != len(data):
        raise ValueError("GLB version/length mismatch")
    pos = 12
    chunks = []
    while pos < total:
        if total - pos < 8:
            raise ValueError("truncated chunk header")
        size, kind = struct.unpack_from("<II", data, pos)
        pos += 8
        if size % 4 or size > total - pos:
            raise ValueError("invalid chunk size")
        chunks.append((kind, data[pos:pos + size]))
        pos += size
    if not chunks or chunks[0][0] != JSON_CHUNK:
        raise ValueError("first chunk must be JSON")
    if len(chunks) > 2 or (len(chunks) == 2 and chunks[1][0] != BIN_CHUNK):
        raise ValueError("unexpected GLB chunk layout")
    try:
        doc = json.loads(chunks[0][1].decode("utf-8").rstrip(" "))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid JSON chunk") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("asset"), dict) or doc["asset"].get("version") != "2.0":
        raise ValueError("not a glTF 2.0 asset")
    for name in ("meshes", "animations", "buffers"):
        if not isinstance(doc.get(name, []), list):
            raise ValueError(f"{name} must be an array")
    for mesh in doc.get("meshes", []):
        if not isinstance(mesh, dict) or not isinstance(mesh.get("primitives", []), list):
            raise ValueError("invalid mesh primitives")
        for primitive in mesh.get("primitives", []):
            if not isinstance(primitive, dict) or not isinstance(primitive.get("targets", []), list):
                raise ValueError("invalid primitive targets")
    buffers = doc.get("buffers", [])
    if len(buffers) > 1 or (buffers and not isinstance(buffers[0], dict)):
        raise ValueError("unsupported embedded buffer layout")
    if len(chunks) == 2 and (not buffers or "uri" in buffers[0]):
        raise ValueError("unreferenced BIN chunk")
    if buffers and "uri" not in buffers[0]:
        if len(chunks) != 2:
            raise ValueError("missing BIN chunk")
        declared = buffers[0].get("byteLength")
        if type(declared) is not int or declared < 0 or not (declared <= len(chunks[1][1]) <= declared + 3):
            raise ValueError("BIN length mismatch")
    return {"meshes": len(doc.get("meshes", [])), "animations": len(doc.get("animations", [])),
            "morph_targets": sum(len(p.get("targets", [])) for m in doc.get("meshes", []) for p in m.get("primitives", [])),
            "bytes": len(data)}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("glb", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_glb(args.glb.read_bytes()), sort_keys=True))


if __name__ == "__main__":
    main()
