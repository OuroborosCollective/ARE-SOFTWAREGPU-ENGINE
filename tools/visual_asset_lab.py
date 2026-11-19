"""Read-only GLB geometry/UV Visual Asset Lab (no PBR or external file loading).

Creates actual SVG projections from indexed GLB BIN vertices. This is a
diagnostic projection, not the renderer's beauty pass or a performance receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

from tools.glb_diagnostic_evidence import (
    MAX_SOURCE_BYTES,
    _embedded_accessor,
    inspect_diagnostic_glb,
)

PROTOCOL = "are.visual-asset-lab.v1"
MAX_VIEW_TRIANGLES = 5000
IMAGE_SIZE = 512


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise ValueError("VISUAL_ASSET_" + code)


def _source_arrays(raw: bytes, max_triangles: int):
    diagnostic = inspect_diagnostic_glb(raw, max_triangles=max_triangles)
    records = diagnostic["primitives"]
    _require(len(records) == 1, "SINGLE_PRIMITIVE_REQUIRED")
    record = records[0]
    topology = record["topology"]
    if topology.get("reason") == "analysis_budget":
        raise ValueError("VISUAL_ASSET_TRIANGLE_BUDGET")
    _require(topology["status"] == "analyzed", "UNSUPPORTED_PRIMITIVE")
    json_length = struct.unpack_from("<I", raw, 12)[0]
    document = json.loads(raw[20:20 + json_length].decode("utf-8"))
    start = 20 + json_length
    _require(start + 8 <= len(raw), "BIN_REQUIRED")
    length, chunk = struct.unpack_from("<II", raw, start)
    _require(chunk == 0x004E4942, "BIN_REQUIRED")
    binary = raw[start + 8:start + 8 + length]
    primitive = document["meshes"][record["mesh"]]["primitives"][record["primitive"]]
    attributes = primitive["attributes"]
    vertices = _embedded_accessor(document, binary, attributes["POSITION"], 3,
                                  (5126,), max_triangles * 3 + 3)
    indices = _embedded_accessor(document, binary, primitive["indices"], 1,
                                (5121, 5123, 5125), max_triangles * 3)
    _require(vertices is not None and indices is not None, "UNSUPPORTED_ACCESSOR")
    _require(all(math.isfinite(c) and abs(c) < 1e7 for v in vertices for c in v),
             "COORDINATE_RANGE")
    faces = [tuple(int(indices[j + k][0]) for k in range(3))
             for j in range(0, len(indices), 3)]
    _require(len(faces) <= max_triangles, "TRIANGLE_BUDGET")
    _require(all(0 <= idx < len(vertices) for face in faces for idx in face),
             "INDEX_OUT_OF_BOUNDS")
    texcoords = None
    if "TEXCOORD_0" in attributes:
        texcoords = _embedded_accessor(document, binary, attributes["TEXCOORD_0"],
                                       2, (5126,), max_triangles * 3 + 3)
        _require(texcoords is not None and len(texcoords) == len(vertices),
                 "UNSUPPORTED_UV_ACCESSOR")
        _require(all(math.isfinite(c) and abs(c) < 1e7 for uv in texcoords for c in uv),
                 "UV_COORDINATE_RANGE")
    return diagnostic, vertices, faces, texcoords


def _normalize(points: list[tuple[float, float]], size: int) -> list[tuple[float, float]]:
    _require(bool(points), "EMPTY_GEOMETRY")
    min_x = min(p[0] for p in points)
    max_x = max(p[0] for p in points)
    min_y = min(p[1] for p in points)
    max_y = max(p[1] for p in points)
    extent = max(max_x - min_x, max_y - min_y, 1e-12)
    scale = (size - 64) / extent
    return [((x - (min_x + max_x) / 2) * scale + size / 2,
             (y - (min_y + max_y) / 2) * scale + size / 2) for x, y in points]


def _svg(points: list[tuple[float, float]], faces: list[tuple[int, int, int]],
         caption: str, *, size: int = IMAGE_SIZE) -> bytes:
    coordinates = _normalize(points, size)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" '
             f'height="{size}" viewBox="0 0 {size} {size}">',
             f'<rect x="0" y="0" width="{size}" height="{size}" fill="#0d1725"/>',
             f'<rect x="16" y="16" width="{size-32}" height="{size-32}" '
             'fill="none" stroke="#39536a" stroke-width="1"/>']
    for a, b, c in faces:
        p = (coordinates[a], coordinates[b], coordinates[c])
        path = " ".join(("M" if i == 0 else "L") + f"{x:.2f},{y:.2f}"
                        for i, (x, y) in enumerate(p)) + " Z"
        parts.append(f'<path d="{path}" fill="none" stroke="#65d5de" '
                     'stroke-opacity=".76" stroke-width=".8"/>')
    parts.append(f'<text x="18" y="{size-18}" fill="#e6eff8" '
                 f'font-family="sans-serif" font-size="12">{caption}</text>')
    parts.append("</svg>")
    return ("\n".join(parts) + "\n").encode("utf-8")


def build_visual_asset_lab(raw: bytes, output_dir: Path, *,
                           max_triangles: int = 3000) -> dict:
    """Generate bounded source-derived wireframe & UV SVG plus source SHA receipt.

    No beauty raster, no PBR evaluation, no filesystem access except explicit
    output folder. Existing outputs cannot be reused or silently overwritten.
    """
    _require(type(raw) in (bytes, bytearray) and len(raw) <= MAX_SOURCE_BYTES,
             "SOURCE_BUDGET")
    _require(type(max_triangles) is int and 1 <= max_triangles <= MAX_VIEW_TRIANGLES,
             "TRIANGLE_BUDGET")
    diagnostic, vertices, faces, texcoords = _source_arrays(raw, max_triangles)
    view = [(x * .85 - z * .45, -y + .2 * x + .25 * z)
            for x, y, z in vertices]
    wireframe = _svg(view, faces, "GEOMETRY ONLY - NO PBR")
    uv_svg = (_svg([(u, -v) for u, v in texcoords], faces, "UV COORDINATES - NOT TEXTURE")
              if texcoords is not None else None)
    target = Path(output_dir)
    _require(not target.is_symlink() and (not target.exists()
             or (target.is_dir() and not any(target.iterdir()))),
             "OUTPUT_NOT_EMPTY_OR_SYMLINK")
    result = {
        "protocol": PROTOCOL,
        "authority": "offline-derived",
        "source": diagnostic["source"],
        "diagnostic": diagnostic,
        "pbr_beauty": "not_executed",
        "verdict": "not_assessed",
        "images": {
            "wireframe": {
                "status": "rendered_geometry_projection",
                "filename": "wireframe.svg",
                "sha256": hashlib.sha256(wireframe).hexdigest(),
            },
            "uv": (
                {"status": "rendered_uv_projection", "filename": "uv.svg",
                 "sha256": hashlib.sha256(uv_svg).hexdigest()}
                if uv_svg is not None else {"status": "not_executed", "reason": "uv_absent"}
            ),
        },
        "scope": "single indexed embedded GLB primitive; source-derived 2D projections",
        "performance": "not_measured",
    }
    target.mkdir(parents=True, exist_ok=True)
    (target / "wireframe.svg").write_bytes(wireframe)
    if uv_svg is not None:
        (target / "uv.svg").write_bytes(uv_svg)
    (target / "visual-asset-receipt.json").write_text(
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("glb", type=Path, help="Local original GLB (never uploaded)")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-triangles", type=int, default=3000)
    args = parser.parse_args(argv)
    try:
        if args.glb.is_symlink() or args.glb.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("VISUAL_ASSET_SOURCE_BUDGET")
        build_visual_asset_lab(args.glb.read_bytes(), args.output_dir,
                               max_triangles=args.max_triangles)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"VISUAL_ASSET_REJECTED:{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
