"""Read completed World Forge GLB exports and compare static geometry silhouettes on CPU."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import numpy as np

from software_gpu import __version__
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex
from software_gpu.integrations.aurion.offline_lod_worker import load_worldforge_glb


def receipt(job):
    path = job / "receipt.json"
    if not re.fullmatch("[0-9a-f]{64}", job.name) or job.is_symlink() or path.is_symlink() or path.stat().st_size > 2**22:
        raise ValueError("Invalid World Forge receipt path")
    raw = path.read_bytes()
    record = json.loads(raw)
    if record["schema"] != "worldforge.blender-export.v1" or record["jobId"] != job.name:
        raise ValueError("World Forge receipt identity mismatch")
    model, = [f for f in record["files"] if f["path"] == "model.glb"]
    if not re.fullmatch("[0-9a-f]{64}", model["sha256"]) or type(model["size"]) is not int:
        raise ValueError("Invalid GLB receipt fields")
    return hashlib.sha256(raw).hexdigest(), model


def cluster(points, faces, cells):
    grid = np.floor((points - points.min(axis=0)) * cells / np.ptp(points, axis=0).max())
    _, index, counts = np.unique(grid.astype(np.int32), axis=0, return_inverse=True, return_counts=True)
    index = index.reshape(-1)
    centers = np.stack([np.bincount(index, weights=column) / counts for column in points.T], axis=1)
    mapped = index[faces]
    valid = ((mapped[:, 0] != mapped[:, 1]) & (mapped[:, 0] != mapped[:, 2]) & (mapped[:, 1] != mapped[:, 2]))
    mapped = mapped[valid]
    _, keep = np.unique(np.sort(mapped, axis=1), axis=0, return_index=True)
    return centers, mapped[np.sort(keep)]


def draw(points, faces, basis, pixels, image):
    clip = points @ basis.T
    a, b, c = (clip[faces[:, j], :2] for j in range(3))
    ab, ac = b-a, c-a
    flip = ab[:, 0]*ac[:, 1] < ab[:, 1]*ac[:, 0]
    oriented = faces.copy()
    oriented[flip] = oriented[flip][:, [0, 2, 1]]
    fb = Framebuffer(pixels, pixels)
    raster = SoftwareRasterizer(fb, num_threads=1)
    try:
        fb.clear(20, 24, 32, 255, depth=1.0)
        raster.draw_mesh([Vertex(v) for v in clip], oriented.tolist(), VertexColorShader())
        fb.save_bmp(str(image))
        return fb.depth_buffer < 1.0
    finally:
        raster.executor.shutdown(wait=True)


def compare(points, faces, output):
    center = (points.max(axis=0) + points.min(axis=0)) * .5
    radius = np.linalg.norm(points - center, axis=1).max()
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError("Geometry has no finite extent")
    points = (points - center) * (.92 / radius)
    levels = [(points, faces), cluster(points, faces, 24), cluster(points, faces, 12)]
    levels_info = [{"level": i, "triangles": len(f), "views": []} for i, (_, f) in enumerate(levels)]
    for view, angle in (("front", .20), ("side", 1.22)):
        ca, sa = np.cos(angle), np.sin(angle)
        cp, sp = np.cos(.22), np.sin(.22)
        basis = np.array([[ca, 0, -sa], [-sa*sp, cp, -ca*sp], [sa*cp, sp, ca*cp]])
        reference = None
        for i, (vertices, triangles) in enumerate(levels):
            name = f"{view}-lod{i}.bmp"
            mask = draw(vertices, triangles, basis, 96, output / name)
            if i == 0:
                if not mask.any():
                    raise ValueError("Original silhouette empty for " + view)
                reference = mask
            union = int((reference | mask).sum())
            levels_info[i]["views"].append({"name": view, "pixels": 96, "image": name,
                "sha256": hashlib.sha256((output / name).read_bytes()).hexdigest(),
                "coveredPixels": int(mask.sum()), "silhouetteIoU": float((reference & mask).sum() / union)})
    candidates = [row for row in levels_info[1:] if 0 < row["triangles"] < len(faces)
                  and min(v["silhouetteIoU"] for v in row["views"]) >= .98]
    return {"levels": levels_info, "recommendedPreviewLevel": min(candidates, key=lambda r: r["triangles"])["level"]
            if candidates else 0, "method": "Static vertex clustering, two 96px orthographic silhouettes, IoU >= 0.98"}


def review(job, destination):
    digest, model = receipt(job)
    # Version and receipt address each independent report. The producer keeps sole ownership of results/.
    destination = destination / job.name / __version__
    destination.mkdir(parents=True, exist_ok=True)
    final = destination / digest
    if (final / "report.json").is_file():
        return final
    with TemporaryDirectory(dir=destination) as temp:
        out = Path(temp) / "review"
        out.mkdir()
        report = {"schema": "are.worldforge.geometry-review.v1", "engineVersion": __version__,
                  "jobId": job.name, "receiptSha256": digest, "modelSha256": model["sha256"]}
        try:
            points, faces, _ = load_worldforge_glb(job / "model.glb", model)
            report.update(compare(points, faces, out), status="reviewed")
        except ValueError as exc:
            # A source mismatch cannot count as an asset review.
            if str(exc) in {"SOURCE_SHA256_MISMATCH", "SOURCE_FILE_MISSING_OR_LINK", "SOURCE_SIZE_MISMATCH"}:
                raise
            report.update(status="manual-review", reason=str(exc))
        (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        try:
            out.rename(final)
        except OSError:
            if not (final / "report.json").is_file():
                raise
    return final


def scan(results, output, limit):
    failures = []
    processed = 0
    for job in sorted(results.iterdir(), key=lambda p: p.stat().st_mtime_ns, reverse=True):
        if not re.fullmatch("[a-f0-9]{64}", job.name) or not (job / "receipt.json").is_file():
            continue
        try:
            digest, _ = receipt(job)
            if (output / job.name / __version__ / digest / "report.json").is_file():
                continue
            print(review(job, output), flush=True)
            processed += 1
        except (ValueError, OSError, KeyError) as error:
            failures.append(f"{job.name}: {error}")
        if processed >= limit:
            break
    if failures:
        raise ValueError("\n".join(failures))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("action", choices=["review", "scan"])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=2)
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.action == "review":
        print(review(args.source, args.output))
    else:
        scan(args.source, args.output, args.limit)


if __name__ == "__main__":
    main()
