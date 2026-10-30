"""Opt-in Wolfram reference view generator; never gameplay or runtime evidence."""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path

SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")

def validate_mesh(data):
    if not isinstance(data, dict) or data.get("schema") != "are.offline-mesh.v1":
        raise ValueError("MULTIVIEW_SCHEMA")
    revision = data.get("source_revision")
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise ValueError("MULTIVIEW_UNPINNED_SOURCE")
    vertices, faces = data.get("vertices"), data.get("triangles")
    if not isinstance(vertices, list) or not 3 <= len(vertices) <= 40000:
        raise ValueError("MULTIVIEW_VERTICES_BOUNDS")
    if not isinstance(faces, list) or not 1 <= len(faces) <= 30000:
        raise ValueError("MULTIVIEW_TRIANGLES_BOUNDS")
    for vertex in vertices:
        if not isinstance(vertex, list) or len(vertex) != 3 or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
            for x in vertex
        ):
            raise ValueError("MULTIVIEW_VERTEX_INVALID")
    for face in faces:
        if not isinstance(face, list) or len(face) != 3 or any(
            isinstance(i, bool) or not isinstance(i, int) or i < 0 or i >= len(vertices)
            for i in face
        ) or len(set(face)) != 3:
            raise ValueError("MULTIVIEW_FACE_INVALID")
    return data

def build_script(mesh, png_path):
    validate_mesh(mesh)
    points = "{" + ",".join("{" + ",".join(format(float(x), ".17g") for x in v) + "}" for v in mesh["vertices"]) + "}"
    faces = "{" + ",".join("{" + ",".join(str(i + 1) for i in f) + "}" for f in mesh["triangles"]) + "}"
    target = json.dumps(str(Path(png_path).resolve()))
    return (
        "(* Non-authoritative offline analysis; no renderer/gameplay receipt. *)\n"
        f"points = {points};\nfaces = {faces};\n"
        "scene = Graphics3D[{GraphicsComplex[points, Polygon[faces]]}, Boxed -> False];\n"
        'views = ResourceFunction["MultiviewGraphics3D", ResourceVersion -> "1.0.0"]'
        '[scene, "ThreeView", "CameraInteraction" -> None, ImageSize -> 960];\n'
        f'If[Export[{target}, views, "PNG"] === $Failed, Exit[4]];\n'
    )

def generate(source, script, png):
    raw = source.read_bytes()
    if len(raw) > 10_000_000:
        raise ValueError("MULTIVIEW_INPUT_TOO_LARGE")
    mesh = validate_mesh(json.loads(raw))
    generated = build_script(mesh, png)
    with script.open("x", encoding="utf-8") as handle:
        handle.write(generated)
    receipt = {
        "schema": "are.wolfram-multiview-receipt.v1",
        "status": "SCRIPT_ONLY_UNRENDERED",
        "declared_revision_verified": False,
        "source_revision": mesh["source_revision"],
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "script_sha256": hashlib.sha256(generated.encode()).hexdigest(),
    }
    receipt_path = script.with_suffix(script.suffix + ".receipt.json")
    with receipt_path.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, sort_keys=True)
    if json.loads(receipt_path.read_text()) != receipt:
        raise RuntimeError("MULTIVIEW_RECEIPT_READBACK")
    return receipt

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--png", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.mesh, args.script, args.png)))
