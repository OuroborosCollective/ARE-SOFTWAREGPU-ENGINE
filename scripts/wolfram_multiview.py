#!/usr/bin/env python3
"""Optional offline static three-view Wolfram inspection script generator.

Never runs Wolfram, touches ARE's rasterizer or claims rendered image evidence.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

REVISION = re.compile(r'(?:[a-f0-9]{40}|[a-f0-9]{64})\Z')


def make_script(mesh, png):
    if not isinstance(mesh, dict) or mesh.get('schema') != 'are.offline-mesh.v1':
        raise ValueError('MULTIVIEW_SCHEMA')
    revision = mesh.get('source_revision')
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise ValueError('MULTIVIEW_UNPINNED_SOURCE')
    points, faces = mesh.get('vertices'), mesh.get('triangles')
    if not isinstance(points, list) or not 3 <= len(points) <= 40000:
        raise ValueError('MULTIVIEW_VERTICES')
    if not isinstance(faces, list) or not 1 <= len(faces) <= 30000:
        raise ValueError('MULTIVIEW_FACES')
    for v in points:
        if not isinstance(v, list) or len(v) != 3 or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
            for x in v
        ):
            raise ValueError('MULTIVIEW_POINT')
    for f in faces:
        if not isinstance(f, list) or len(f) != 3 or len(set(f)) != 3 or any(
            isinstance(i, bool) or not isinstance(i, int) or i < 0 or i >= len(points)
            for i in f
        ):
            raise ValueError('MULTIVIEW_FACE')
    vertices = '{' + ','.join('{' + ','.join(format(float(x), '.17g') for x in v) + '}'
                             for v in points) + '}'
    polygons = '{' + ','.join('{' + ','.join(str(i + 1) for i in f) + '}'
                             for f in faces) + '}'
    target = json.dumps(str(Path(png).resolve()), ensure_ascii=True)
    return ('(* Offline script only. Not a rendered image or gameplay receipt. *)\n'
            f'points = {vertices};\nfaces = {polygons};\n'
            'scene = Graphics3D[{EdgeForm[GrayLevel[0.4]],'
            ' FaceForm[GrayLevel[0.8]], GraphicsComplex[points, Polygon[faces]]}];\n'
            'views = ResourceFunction["MultiviewGraphics3D",'
            ' ResourceVersion -> "1.0.0"][scene, "ThreeView",'
            ' "CameraInteraction" -> None, ImageSize -> 960];\n'
            f'If[Export[{target}, views, "PNG"] === $Failed, Exit[4]];\n')


def generate(input_path, script_path, png_path):
    raw = input_path.read_bytes()
    if len(raw) > 10_000_000:
        raise ValueError('MULTIVIEW_INPUT_TOO_LARGE')
    mesh = json.loads(raw)
    script = make_script(mesh, png_path).encode('utf-8')
    if png_path.exists():
        raise FileExistsError('MULTIVIEW_OUTPUT_ALREADY_EXISTS')
    with script_path.open('xb') as out:
        out.write(script)
    receipt = {
        'schema': 'are.wolfram-multiview-script.v1',
        'status': 'SCRIPT_ONLY_UNRENDERED',
        'source_revision': mesh['source_revision'],
        'declared_revision_verified': False,
        'input_sha256': hashlib.sha256(raw).hexdigest(),
        'script_sha256': hashlib.sha256(script).hexdigest(),
        'triangle_count': len(mesh['triangles']),
    }
    target = script_path.with_suffix(script_path.suffix + '.receipt.json')
    with target.open('x', encoding='utf-8') as out:
        json.dump(receipt, out, sort_keys=True, indent=2)
        out.write('\n')
    if json.loads(target.read_text(encoding='utf-8')) != receipt:
        raise RuntimeError('MULTIVIEW_READBACK')
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mesh', type=Path, required=True)
    p.add_argument('--script', type=Path, required=True)
    p.add_argument('--png', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(generate(a.mesh, a.script, a.png), sort_keys=True))


if __name__ == '__main__':
    main()
