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
from software_gpu.integrations.aurion.offline_lod_worker import load_worldforge_glb, MAX_GLB_BYTES


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


class WorldForgeBudgetRefusal(ValueError):
    """Metadata-only refusal, never a validated source or geometry report."""
    def __init__(self, job, digest, model, size):
        super().__init__("GLB_REVIEW_SIZE_LIMIT")
        self.diagnostic = {
            "schema": "are.worldforge.admission.v1", "engineVersion": __version__,
            "jobId": job.name, "receiptSha256": digest,
            "declaredModelSha256": model["sha256"], "observedBytes": size,
            "maxReviewBytes": MAX_GLB_BYTES, "status": "not-admitted",
            "reason": str(self), "manualReviewRequired": True,
            "sourceHashVerified": False, "geometryReviewed": False,
        }


def _check_review_source(job, digest, model):
    """Refuse large sources before fresh import or any report-cache lookup."""
    source = job / "model.glb"
    if source.is_symlink() or not source.is_file():
        raise ValueError("SOURCE_FILE_MISSING_OR_LINK")
    size = source.stat().st_size
    if size != model["size"]:
        raise ValueError("SOURCE_SIZE_MISMATCH")
    if size > MAX_GLB_BYTES:
        # No source open/hash, geometry parse, or persisted review takes place.
        # Rechecking metadata is not a claim that these bytes match the receipt.
        raise WorldForgeBudgetRefusal(job, digest, model, size)


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


def _verified_cached_review(final, job, digest, model):
    """A cached report is never authority without current source and output hashes."""
    # Cached reviews are an admission surface too. Never hash or bless a
    # source beyond the same 8 MiB GLB2 limit required by a fresh import.
    if type(model.get("size")) is not int or not 32 <= model["size"] <= MAX_GLB_BYTES:
        raise ValueError("GLB_REVIEW_SIZE_LIMIT")
    source = job / "model.glb"
    if source.is_symlink() or not source.is_file():
        raise ValueError("SOURCE_FILE_MISSING_OR_LINK")
    if source.stat().st_size != model["size"]:
        raise ValueError("SOURCE_SIZE_MISMATCH")
    state = hashlib.sha256()
    with source.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            state.update(part)
    if state.hexdigest() != model["sha256"]:
        raise ValueError("SOURCE_SHA256_MISMATCH")
    report_path = final / "report.json"
    if report_path.is_symlink() or not report_path.is_file() or report_path.stat().st_size > (1 << 18):
        raise ValueError("WORLD_FORGE_CACHE_INVALID")
    try:
        report = json.loads(report_path.read_text("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("WORLD_FORGE_CACHE_INVALID") from exc
    if (not isinstance(report, dict) or
            report.get("schema") != "are.worldforge.geometry-review.v1" or
            report.get("engineVersion") != __version__ or
            report.get("jobId") != job.name or
            report.get("receiptSha256") != digest or
            report.get("modelSha256") != model["sha256"]):
        raise ValueError("WORLD_FORGE_CACHE_INVALID")
    if report.get("status") == "reviewed":
        levels = report.get("levels")
        if not isinstance(levels, list) or len(levels) != 3:
            raise ValueError("WORLD_FORGE_CACHE_INVALID")
        for i, level in enumerate(levels):
            if not isinstance(level, dict) or level.get("level") != i:
                raise ValueError("WORLD_FORGE_CACHE_INVALID")
            views = level.get("views")
            if not isinstance(views, list) or len(views) != 2:
                raise ValueError("WORLD_FORGE_CACHE_INVALID")
            for kind, view in zip(("front", "side"), views):
                expected_name = f"{kind}-lod{i}.bmp"
                if not isinstance(view, dict) or view.get("image") != expected_name or view.get("name") != kind:
                    raise ValueError("WORLD_FORGE_CACHE_INVALID")
                image = final / expected_name
                # The producer renders only 96x96 BMPs. A tampered cache must
                # not allocate unbounded memory during integrity readback.
                if (image.is_symlink() or not image.is_file() or
                        not 0 < image.stat().st_size <= 128 * 1024):
                    raise ValueError("WORLD_FORGE_CACHE_INVALID")
                image_sha = hashlib.sha256()
                with image.open("rb") as stream:
                    for part in iter(lambda: stream.read(64 * 1024), b""):
                        image_sha.update(part)
                if image_sha.hexdigest() != view.get("sha256"):
                    raise ValueError("WORLD_FORGE_CACHE_INVALID")
    elif report.get("status") != "manual-review" or not isinstance(report.get("reason"), str):
        raise ValueError("WORLD_FORGE_CACHE_INVALID")
    return final


def review(job, destination):
    digest, model = receipt(job)
    _check_review_source(job, digest, model)
    # Version and receipt address each independent report. The producer keeps sole ownership of results/.
    destination = destination / job.name / __version__
    destination.mkdir(parents=True, exist_ok=True)
    final = destination / digest
    if (final / "report.json").is_file():
        return _verified_cached_review(final, job, digest, model)
    with TemporaryDirectory(dir=destination) as temp:
        out = Path(temp) / "review"
        out.mkdir()
        report = {"schema": "are.worldforge.geometry-review.v1", "engineVersion": __version__,
                  "jobId": job.name, "receiptSha256": digest, "modelSha256": model["sha256"]}
        try:
            points, faces, _ = load_worldforge_glb(job / "model.glb", model)
            report.update(compare(points, faces, out), status="reviewed")
        except ValueError as exc:
            # Only structurally valid but unsupported/over-budget static
            # geometry may be marked manual-review. Corrupt or ambiguous
            # containers, source hashes, accessors and external URIs fail closed.
            manual_reasons = {"STATIC_GEOMETRY_REVIEW_REQUIRED", "MESH_TOO_LARGE",
                              "SCENE_COMPLEXITY_LIMIT",
                              "NO_SUPPORTED_TRIANGLE_GEOMETRY"}
            if str(exc) not in manual_reasons:
                raise
            report.update(status="manual-review", reason=str(exc))
        (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        try:
            out.rename(final)
        except OSError:
            if not (final / "report.json").is_file():
                raise
            # Concurrent producers must never promote an unverified cache.
            return _verified_cached_review(final, job, digest, model)
    return final


def scan(results, output, limit):
    failures = []
    processed = 0
    for job in sorted(results.iterdir(), key=lambda p: p.stat().st_mtime_ns, reverse=True):
        if not re.fullmatch("[a-f0-9]{64}", job.name) or not (job / "receipt.json").is_file():
            continue
        try:
            digest, model = receipt(job)
            _check_review_source(job, digest, model)
            cached = output / job.name / __version__ / digest
            if (cached / "report.json").is_file():
                # Cache skips may not silently hide a changed source or
                # tampered six-view preview from the incremental scanner.
                _verified_cached_review(cached, job, digest, model)
                continue
            print(review(job, output), flush=True)
            processed += 1
        except WorldForgeBudgetRefusal as error:
            # A rejected/unverified input does not consume a geometry-review
            # slot. Invalid receipts, changed sizes/hashes and corrupt inputs
            # still take the failure path below.
            print(json.dumps(error.diagnostic, sort_keys=True), flush=True)
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
        try:
            print(review(args.source, args.output))
        except WorldForgeBudgetRefusal as error:
            print(json.dumps(error.diagnostic, sort_keys=True))
    else:
        scan(args.source, args.output, args.limit)


if __name__ == "__main__":
    main()
