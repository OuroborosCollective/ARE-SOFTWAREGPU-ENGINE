"""Phase 4: isolated Aurion offline render/benchmark worker (issue #6).

Contract `are.aurion.offline-render-job.v1`:
  IN   revisioned mesh/camera/render fixtures with hashes, seed/config and
       CPU/RAM/deadline budgets.
  OUT  reproducible derived render artifact, output digest, source revision
       and a test/time/error receipt (`are.aurion.offline-render-receipt.v2`).

The worker is read-only: no canonical world state, no NPC/physics authority,
no gameplay persistence, no 100-ms game tick, no network service. Isolation
is a killable child process (`_offline_child.py` bootstrap) whose Linux
rlimits (RLIMIT_AS for RAM, RLIMIT_CPU as kernel backstop) are applied BEFORE
any heavy import, plus a parent-enforced wall-clock deadline and a
cooperative CPU-budget check between render repeats.

Fixture kinds:
  - "procedural": deterministic seeded mesh (SHA-256 counter PRNG), fully
    reproducible in CI without binary assets.
  - "glb": SHA-256 pinned binary glTF2 file, parsed by the Phase-1 loader.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import struct
import subprocess
import sys
import tempfile
import time

import numpy as np

from software_gpu.integrations.aurion.offline_lod_worker import (
    MAX_GLB_BYTES,
    _camera_transform,
    _clean_number,
    _FlatShader,
    load_glb,
)

JOB_PROTOCOL = "are.aurion.offline-render-job.v1"
RECEIPT_PROTOCOL = "are.aurion.offline-render-receipt.v2"
AUTHORITY = "offline-read-only"

PIXELS_MIN, PIXELS_MAX = 32, 256
REPEATS_MIN, REPEATS_MAX = 2, 5
DEADLINE_MIN_S, DEADLINE_MAX_S = 0.02, 300.0
MEMORY_MIN_MB, MEMORY_MAX_MB = 32, 4096
CPU_MIN_S, CPU_MAX_S = 0.05, 600.0
RINGS_MIN, RINGS_MAX = 2, 64
SEGMENTS_MIN, SEGMENTS_MAX = 3, 128
BACKENDS = ("tiles", "tiles-jit", "bands")
FIXTURE_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
GLB_NAME_RE = re.compile(r"[A-Za-z0-9_()]+\.glb\Z")
FLAT_COLOR = np.asarray([0.80, 0.70, 0.45], dtype=np.float32)
MESH_RADIUS = 0.55  # keeps orthographic |depth| < 1 for the shared camera model

_SIGXCPU = 24  # signal.SIGXCPU on POSIX; kept literal so Windows can import this


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _is_int(value) -> bool:
    return type(value) is int


def _is_number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


# ---------------------------------------------------------------------------
# Fixture construction
# ---------------------------------------------------------------------------

def _prng_floats(seed: int, label: bytes, count: int) -> np.ndarray:
    """Deterministic SHA-256 counter-mode stream in [0, 1). No numpy RNG."""
    buf = b""
    counter = 0
    while len(buf) < count * 4:
        buf += hashlib.sha256(
            struct.pack("<Q", seed) + label + struct.pack("<I", counter)
        ).digest()
        counter += 1
    return np.frombuffer(buf[: count * 4], dtype="<u4").astype(np.float64) / 2**32


def build_procedural_mesh(seed: int, rings: int, segments: int):
    """Deterministic seeded deformed sphere; pure SHA-256 + trig, CI-safe."""
    noise = _prng_floats(seed, b"aurion-phase4-mesh", (rings + 1) * segments)
    vertices = np.empty(((rings + 1) * segments, 3), dtype=np.float64)
    k = 0
    for i in range(rings + 1):
        theta = math.pi * i / rings
        sin_t, cos_t = math.sin(theta), math.cos(theta)
        for j in range(segments):
            phi = 2.0 * math.pi * j / segments
            radius = MESH_RADIUS * (1.0 + 0.30 * (2.0 * noise[k] - 1.0))
            vertices[k] = (radius * sin_t * math.cos(phi),
                           radius * cos_t,
                           radius * sin_t * math.sin(phi))
            k += 1
    faces = np.empty((rings * segments * 2, 3), dtype=np.int32)
    k = 0
    for i in range(rings):
        for j in range(segments):
            a = i * segments + j
            b = i * segments + (j + 1) % segments
            c = (i + 1) * segments + j
            d = (i + 1) * segments + (j + 1) % segments
            faces[k] = (a, c, b)
            faces[k + 1] = (b, c, d)
            k += 2
    return vertices.astype(np.float32), faces


def mesh_digest(vertices: np.ndarray, faces: np.ndarray) -> str:
    return _sha256(np.ascontiguousarray(vertices).astype("<f4").tobytes()
                   + np.ascontiguousarray(faces).astype("<i4").tobytes())


# ---------------------------------------------------------------------------
# Job contract validation (fail-closed, specific error codes)
# ---------------------------------------------------------------------------

def validate_job(job) -> dict:
    if not isinstance(job, dict):
        raise ValueError("JOB_INVALID")
    if job.get("protocol") != JOB_PROTOCOL:
        raise ValueError("JOB_PROTOCOL_INVALID")
    if job.get("authority") != AUTHORITY:
        raise ValueError("JOB_AUTHORITY_INVALID")
    description = job.get("description", "")
    if not isinstance(description, str) or len(description) > 200:
        raise ValueError("JOB_DESCRIPTION_INVALID")

    fixture = job.get("fixture")
    if not isinstance(fixture, dict):
        raise ValueError("FIXTURE_INVALID")
    fixture_id = fixture.get("fixture_id")
    if not isinstance(fixture_id, str) or not FIXTURE_ID_RE.fullmatch(fixture_id):
        raise ValueError("FIXTURE_ID_INVALID")
    kind = fixture.get("kind")
    if kind == "procedural":
        seed = fixture.get("seed")
        rings = fixture.get("rings")
        segments = fixture.get("segments")
        if not _is_int(seed) or not 0 <= seed < 2**31:
            raise ValueError("SEED_INVALID")
        if not _is_int(rings) or not RINGS_MIN <= rings <= RINGS_MAX:
            raise ValueError("MESH_RINGS_INVALID")
        if not _is_int(segments) or not SEGMENTS_MIN <= segments <= SEGMENTS_MAX:
            raise ValueError("MESH_SEGMENTS_INVALID")
    elif kind == "glb":
        entry = fixture.get("entry")
        name = fixture.get("file")
        if not isinstance(name, str) or not GLB_NAME_RE.fullmatch(name):
            raise ValueError("GLB_NAME_INVALID")
        if not isinstance(entry, dict):
            raise ValueError("GLB_ENTRY_INVALID")
        digest = entry.get("source_sha256")
        if (not _is_int(entry.get("bytes"))
                or not 32 <= entry["bytes"] <= MAX_GLB_BYTES
                or not isinstance(digest, str) or len(digest) != 64
                or not _is_int(entry.get("vertices")) or entry["vertices"] < 1
                or not _is_int(entry.get("triangles")) or entry["triangles"] < 1
                or not _is_int(entry.get("meshes")) or entry["meshes"] < 0
                or not _is_int(entry.get("materials")) or entry["materials"] < 0
                or not _is_int(entry.get("images")) or entry["images"] < 0):
            raise ValueError("GLB_ENTRY_INVALID")
    else:
        raise ValueError("FIXTURE_KIND_UNSUPPORTED")

    camera = job.get("camera")
    if not isinstance(camera, dict):
        raise ValueError("CAMERA_INVALID")
    for key, low, high in (("yaw_degrees", -180, 180), ("pitch_degrees", -85, 85),
                           ("center_y", -100, 100), ("x_half_extent", .001, 200),
                           ("y_half_extent", .001, 200)):
        if key not in camera:
            raise ValueError("CAMERA_INVALID")
        _clean_number(camera[key], low, high)  # raises CAMERA_PARAMETER_OUT_OF_RANGE

    render = job.get("render")
    if not isinstance(render, dict):
        raise ValueError("RENDER_CONFIG_INVALID")
    if not _is_int(render.get("pixels")) or not PIXELS_MIN <= render["pixels"] <= PIXELS_MAX:
        raise ValueError("PIXEL_BUDGET_INVALID")
    if not _is_int(render.get("repeats")) or not REPEATS_MIN <= render["repeats"] <= REPEATS_MAX:
        raise ValueError("REPEAT_BUDGET_INVALID")
    if render.get("backend") not in BACKENDS:
        raise ValueError("BACKEND_UNSUPPORTED")

    budget = job.get("budget")
    if not isinstance(budget, dict):
        raise ValueError("RESOURCE_BUDGET_INVALID")
    if (not _is_number(budget.get("deadline_seconds"))
            or not DEADLINE_MIN_S <= budget["deadline_seconds"] <= DEADLINE_MAX_S
            or not _is_int(budget.get("memory_mb"))
            or not MEMORY_MIN_MB <= budget["memory_mb"] <= MEMORY_MAX_MB
            or not _is_number(budget.get("cpu_seconds"))
            or not CPU_MIN_S <= budget["cpu_seconds"] <= CPU_MAX_S):
        raise ValueError("RESOURCE_BUDGET_INVALID")
    return job


# ---------------------------------------------------------------------------
# Render core (runs inside the isolated child)
# ---------------------------------------------------------------------------

def _orient_double_sided(clip: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Same winding convention as the Phase-1 LOD worker (double-sided mesh)."""
    screens = clip[:, :2]
    ab = screens[faces[:, 1]] - screens[faces[:, 0]]
    ac = screens[faces[:, 2]] - screens[faces[:, 0]]
    orient = ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]
    faces = faces.copy()
    back = orient < 0
    faces[back, 1], faces[back, 2] = faces[back, 2].copy(), faces[back, 1].copy()
    return faces


def _render_mesh(vertices, faces, camera, backend, pixels, repeats,
                 cpu_seconds, out_dir, image_stem):
    from software_gpu.graphics.framebuffer import Framebuffer
    from software_gpu.graphics.rasterizer import SoftwareRasterizer
    from software_gpu.graphics.shader import Vertex

    clip = _camera_transform(vertices, camera)
    faces = _orient_double_sided(clip, faces)
    shader = _FlatShader()
    mesh = [Vertex(v, color=FLAT_COLOR) for v in clip]
    fb = Framebuffer(pixels, pixels)
    # tile_size=32: measured optimum of the 8/16/32/64 matrix (Slice B);
    # output is byte-identical at every size, 16->32 saves 1.09-1.16x wall.
    render = SoftwareRasterizer(fb, backend=backend, num_threads=1, tile_size=32)
    samples, digests, covered = [], [], []
    try:
        for _ in range(repeats):
            if time.process_time() > cpu_seconds:
                raise ValueError("WORKER_CPU_BUDGET_EXCEEDED")
            fb.clear(16, 25, 38, 255, depth=1.0)
            t0 = time.perf_counter_ns()
            c0 = time.process_time_ns()
            render.draw_mesh(mesh, [tuple(int(i) for i in f) for f in faces], shader)
            samples.append({"wall_ms": round((time.perf_counter_ns() - t0) / 1e6, 3),
                            "cpu_ms": round((time.process_time_ns() - c0) / 1e6, 3)})
            digests.append(_sha256(fb.color_buffer.tobytes() + fb.depth_buffer.tobytes()))
            covered.append(int(np.count_nonzero(fb.depth_buffer < 1.0)))
        if len(set(digests)) != 1 or max(covered) <= 0:
            raise ValueError("REPLAY_IMAGE_HASH_MISMATCH_OR_EMPTY")
        out_dir.mkdir(parents=True, exist_ok=True)
        image_path = out_dir / (image_stem + "_ARE.bmp")
        fb.save_bmp(str(image_path))
        image_sha = _sha256(image_path.read_bytes())
    finally:
        render.executor.shutdown(wait=True)
    peak_rss_bytes = None
    if sys.platform.startswith("linux"):
        import resource
        peak_rss_bytes = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    return {
        "replay_hash_sha256": digests[0], "repeat_byte_identical": True,
        "covered_pixels": covered[0], "pixels": pixels, "repeats": repeats,
        "median_wall_ms": round(statistics.median(x["wall_ms"] for x in samples), 3),
        "samples": samples, "image_bmp_sha256": image_sha,
        "image_file": image_path.name, "peak_rss_bytes": peak_rss_bytes,
        "cpu_seconds_total": round(time.process_time(), 3),
        "pipeline": "ARE %s CPU / flat color / geometry only" % backend,
        "texture_pbr_equivalence": False,
    }


def _load_fixture_mesh(fixture, model_dir):
    """Returns (vertices, faces, fixture_receipt_fields)."""
    if fixture["kind"] == "procedural":
        vertices, faces = build_procedural_mesh(fixture["seed"], fixture["rings"],
                                                fixture["segments"])
        fields = {"kind": "procedural", "seed": fixture["seed"],
                  "rings": fixture["rings"], "segments": fixture["segments"]}
    else:
        if model_dir is None or not Path(model_dir).is_dir():
            raise ValueError("MODEL_DIRECTORY_UNAVAILABLE")
        path = (Path(model_dir) / fixture["file"]).resolve()
        if not str(path).startswith(str(Path(model_dir).resolve()) + os.sep):
            raise ValueError("MODEL_PATH_ESCAPE")
        entry = dict(fixture["entry"])
        entry.setdefault("lod", 0)
        entry["file"] = fixture["file"]
        vertices, faces, digest = load_glb(path, entry)
        fields = {"kind": "glb", "file": fixture["file"],
                  "source_sha256": digest, "source_bytes": entry["bytes"]}
    fields["mesh_sha256"] = mesh_digest(vertices, faces)
    fields["vertices"] = int(len(vertices))
    fields["triangles"] = int(len(faces))
    return vertices, faces, fields


def execute_job(job, model_dir, out_dir) -> dict:
    """Child-side: build fixture, render with budgets, return outcome record."""
    fixture = job["fixture"]
    vertices, faces, fixture_fields = _load_fixture_mesh(fixture, model_dir)
    outcome = _render_mesh(vertices, faces, job["camera"],
                           job["render"]["backend"], job["render"]["pixels"],
                           job["render"]["repeats"], job["budget"]["cpu_seconds"],
                           out_dir, fixture["fixture_id"])
    outcome["fixture"] = fixture_fields
    return outcome


def compose_receipt(job, job_sha256, outcome, errors) -> dict:
    body = {
        "protocol": RECEIPT_PROTOCOL, "authority": AUTHORITY,
        "job_sha256": job_sha256,
        "repo_revision": os.environ.get("GITHUB_SHA", "local"),
        "python": platform.python_version(), "os": platform.platform(),
        "gpu_required": False,
        "pbr_or_aurion_renderer_equivalence": "NOT_ESTABLISHED",
        "budget": job["budget"],
        "outcome": outcome,
        "errors": errors,
    }
    if outcome is not None:
        peak = outcome.get("peak_rss_bytes")
        body["budget_compliance"] = {
            "deadline_ok": outcome["median_wall_ms"] <= job["budget"]["deadline_seconds"] * 1000,
            "memory_ok": peak is None or peak <= job["budget"]["memory_mb"] * 1024**2,
            "cpu_ok": outcome["cpu_seconds_total"] <= job["budget"]["cpu_seconds"] * 2,
        }
    body["receipt_sha256"] = _sha256(_canonical(body))
    return body


_CHILD_BOOTSTRAP = Path(__file__).resolve().with_name("_offline_child.py")


def _write_receipt(out_path: Path, receipt: dict):
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "aurion-phase4-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_job(job, model_dir=None, out_dir=None) -> dict:
    """Validate, run in a limit-bound child process, enforce the wall-clock
    deadline, then compose and write the receipt (success or failure)."""
    validate_job(job)
    job_sha256 = _sha256(_canonical(job))
    out_path = Path(out_dir) if out_dir is not None else Path.cwd()
    budget = job["budget"]
    deadline = float(budget["deadline_seconds"])
    outcome, errors = None, []
    proc = None
    try:
        with tempfile.TemporaryDirectory(prefix="aurion-phase4-") as work:
            work_path = Path(work)
            job_path = work_path / "job.json"
            reply_path = work_path / "reply.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            env = dict(os.environ)
            pkg_root = str(Path(__file__).resolve().parents[3])
            env["PYTHONPATH"] = (pkg_root + os.pathsep + env["PYTHONPATH"]
                                 if env.get("PYTHONPATH") else pkg_root)
            proc = subprocess.Popen(
                [sys.executable, str(_CHILD_BOOTSTRAP), str(job_path),
                 str(model_dir) if model_dir is not None else "-",
                 str(out_path), str(reply_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=env)
            try:
                proc.wait(timeout=deadline)
            except subprocess.TimeoutExpired:
                raise TimeoutError("WORKER_DEADLINE_EXCEEDED") from None
            reply = None
            if reply_path.is_file():
                try:
                    reply = json.loads(reply_path.read_text("utf-8"))
                except (ValueError, OSError):
                    reply = None
            if reply is None:
                if proc.returncode == -_SIGXCPU:
                    raise ValueError("WORKER_CPU_LIMIT_EXCEEDED")
                raise ValueError("WORKER_CRASHED:exitcode=%s" % proc.returncode)
            if "ok" not in reply:
                family = reply.get("family", "UNKNOWN")
                if re.fullmatch(r"[A-Z0-9_]{3,120}", family):
                    raise ValueError(family)
                raise ValueError("WORKER_FAILED:" + reply.get("error", "UNKNOWN")
                                 + ":" + family[:60])
            outcome = reply["ok"]
            peak = outcome.get("peak_rss_bytes")
            if peak is not None and peak > int(budget["memory_mb"]) * 1024**2:
                raise ValueError("WORKER_MEMORY_BUDGET_EXCEEDED")
    except (ValueError, TimeoutError) as exc:
        errors.append({"class": str(exc).split(":")[0], "detail": str(exc)[:120]})
        _write_receipt(out_path, compose_receipt(job, job_sha256, None, errors))
        raise
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
    receipt = compose_receipt(job, job_sha256, outcome, errors)
    _write_receipt(out_path, receipt)
    return receipt


# ---------------------------------------------------------------------------
# Benchmark gate: proof of benefit vs. the existing CPU path, else hold
# ---------------------------------------------------------------------------

def compare_backends(vertices, faces, camera, pixels=128, repeats=3,
                     backends=("bands", "tiles")) -> dict:
    """Same-host sequential A/B of the historical band renderer (existing CPU
    path) versus the tile backend. Requires byte-identical color+depth."""
    results = {}
    for backend in backends:
        with _temp_out() as tmp:
            record = _render_mesh(vertices, faces, camera, backend, pixels,
                                  repeats, cpu_seconds=CPU_MAX_S,
                                  out_dir=tmp, image_stem="cmp_" + backend)
        results[backend] = record
    ref = results[backends[0]]
    new = results[backends[1]]
    image_identical = ref["replay_hash_sha256"] == new["replay_hash_sha256"]
    base = ref["median_wall_ms"]
    speedup = round(base / new["median_wall_ms"], 4) if new["median_wall_ms"] > 0 else None
    return {"backends": results, "reference_backend": backends[0],
            "candidate_backend": backends[1], "image_identical": image_identical,
            "speedup": speedup}


class _temp_out:
    def __init__(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)

    def __enter__(self):
        return self.path

    def __exit__(self, *exc):
        self._tmp.cleanup()


def decide_activation(speedup, image_identical, min_speedup=1.10) -> dict:
    """Contract gate: no activation without proven benefit on identical images."""
    reasons = []
    if not image_identical:
        reasons.append("IMAGE_MISMATCH_BETWEEN_BACKENDS")
    if speedup is None:
        reasons.append("SPEEDUP_UNMEASURABLE")
    elif speedup < 1.0:
        reasons.append("SLOWER_THAN_EXISTING_CPU_PATH")
    elif speedup < min_speedup:
        reasons.append("BENEFIT_BELOW_THRESHOLD:%.2f<%.2f" % (speedup, min_speedup))
    activate = image_identical and speedup is not None and speedup >= min_speedup
    if activate:
        reasons.append("REAL_BENEFIT_ON_IDENTICAL_IMAGES:%.2fx" % speedup)
    return {"decision": "activate" if activate else "hold",
            "min_speedup": min_speedup, "speedup": speedup,
            "image_identical": image_identical, "reasons": reasons}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job", type=Path, required=True,
                   help="Path to an are.aurion.offline-render-job.v1 JSON file")
    p.add_argument("--model-dir", type=Path, default=None,
                   help="Directory with pinned GLB binaries (kind=glb only)")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--benchmark", action="store_true",
                   help="Also run bands-vs-tiles A/B and the activation gate")
    p.add_argument("--min-speedup", type=float, default=1.10)
    args = p.parse_args()
    job = json.loads(args.job.read_text("utf-8"))
    try:
        receipt = run_job(job, args.model_dir, args.output_dir)
    except (ValueError, TimeoutError) as exc:
        print("AURION_PHASE4_FAIL " + str(exc).split(":")[0], file=sys.stderr)
        raise SystemExit(2)
    if args.benchmark:
        fixture = job["fixture"]
        vertices, faces, _ = _load_fixture_mesh(fixture, args.model_dir)
        comparison = compare_backends(vertices, faces, job["camera"],
                                      pixels=job["render"]["pixels"],
                                      repeats=job["render"]["repeats"])
        comparison["activation"] = decide_activation(
            comparison["speedup"], comparison["image_identical"], args.min_speedup)
        receipt["benchmark"] = comparison
        receipt["receipt_sha256"] = _sha256(_canonical(
            {k: v for k, v in receipt.items() if k != "receipt_sha256"}))
        (args.output_dir / "aurion-phase4-receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("AURION_PHASE4_OK " + receipt["receipt_sha256"])


if __name__ == "__main__":
    main()
