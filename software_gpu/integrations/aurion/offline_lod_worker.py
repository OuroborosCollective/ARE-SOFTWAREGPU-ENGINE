"""CPU-only, read-only Aurion GLB LOD verification worker.

Requires exact SHA-256 pinned GLB2 input files. Runs each LOD in a killable
process; no network, no Aurion dependency, no world-state mutation.
Supports geometry + constant material color ONLY, not full glTF/PBR/animations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import platform
import queue
import struct
import sys
import time

import numpy as np

PROTOCOL = "are.aurion.street-lamp.glb-fixture.v1"
RECEIPT_PROTOCOL = "are.aurion.offline-render-receipt.v1"
MAX_GLB_BYTES = 8_388_608
MAX_VERTICES = 25_000
MAX_TRIANGLES = 25_000

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _clean_number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("CAMERA_PARAMETER_OUT_OF_RANGE")
    return float(value)

def _read_accessor(doc, binary, accessor_index, typ):
    accessors = doc.get("accessors", [])
    if not isinstance(accessor_index, int) or not 0 <= accessor_index < len(accessors):
        raise ValueError("ACCESSOR_INDEX_INVALID")
    a = accessors[accessor_index]
    if a.get("sparse") is not None:
        raise ValueError("SPARSE_ACCESSOR_UNSUPPORTED")
    if a.get("type") != typ:
        raise ValueError("ACCESSOR_TYPE_INVALID")
    kind = a.get("componentType")
    if typ == "VEC3" and kind == 5126:
        dtype = np.dtype("<f4")
        components = 3
    elif typ == "SCALAR" and kind in (5123, 5125):
        dtype = np.dtype("<u2" if kind == 5123 else "<u4")
        components = 1
    else:
        raise ValueError("ACCESSOR_COMPONENT_UNSUPPORTED")
    count = a.get("count")
    ceiling = MAX_VERTICES if typ == "VEC3" else MAX_TRIANGLES * 3
    if type(count) is not int or not 1 <= count <= ceiling:
        raise ValueError("ACCESSOR_COUNT_LIMIT")
    views = doc.get("bufferViews", [])
    vi = a.get("bufferView")
    if type(vi) is not int or not 0 <= vi < len(views):
        raise ValueError("BUFFER_VIEW_INVALID")
    view = views[vi]
    if view.get("buffer") != 0:
        raise ValueError("EXTERNAL_BUFFER_UNSUPPORTED")
    elem_bytes = components * dtype.itemsize
    stride = view.get("byteStride", elem_bytes)
    offset = view.get("byteOffset", 0)
    inner = a.get("byteOffset", 0)
    span = view.get("byteLength")
    if any(type(v) is not int for v in (stride, offset, inner, span)):
        raise ValueError("ACCESSOR_LAYOUT_INVALID")
    if (stride < elem_bytes or stride > 256 or stride % dtype.itemsize or
        offset < 0 or inner < 0 or span < 0 or
        inner + (count - 1) * stride + elem_bytes > span or
        offset + span > len(binary) or offset + inner + (count - 1) * stride + elem_bytes > len(binary)):
        raise ValueError("ACCESSOR_BYTES_OUT_OF_BOUNDS")
    begin = offset + inner
    return np.ndarray(shape=(count, components), dtype=dtype, buffer=binary,
                      offset=begin, strides=(stride, dtype.itemsize)).copy()


def _node_matrix(node):
    if "matrix" in node:
        m = node["matrix"]
        if not isinstance(m, list) or len(m) != 16 or not all(
                isinstance(x, (int, float)) and math.isfinite(x) for x in m):
            raise ValueError("NODE_MATRIX_INVALID")
        return np.asarray(m, dtype=np.float64).reshape(4, 4, order="F")
    t = node.get("translation", [0, 0, 0])
    s = node.get("scale", [1, 1, 1])
    q = node.get("rotation", [0, 0, 0, 1])
    if not (len(t) == 3 and len(s) == 3 and len(q) == 4):
        raise ValueError("NODE_TRS_INVALID")
    vals = np.asarray([*t, *s, *q], dtype=np.float64)
    if not np.isfinite(vals).all() or np.max(np.abs(vals)) > 1e6:
        raise ValueError("NODE_TRS_NONFINITE")
    x, y, z, w = q
    norm = x*x+y*y+z*z+w*w
    if norm < 1e-16:
        raise ValueError("NODE_QUATERNION_INVALID")
    x, y, z, w = np.asarray(q, dtype=np.float64) / np.sqrt(norm)
    rot = np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w),   2*(x*z+y*w)],
        [2*(x*y+z*w),   1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w),   2*(y*z+x*w),   1-2*(x*x+y*y)]], dtype=np.float64)
    m = np.eye(4, dtype=np.float64)
    m[:3, :3] = rot @ np.diag(s)
    m[:3, 3] = t
    return m


def load_glb(path: Path, expected: dict):
    if path.is_symlink() or not path.is_file():
        raise ValueError("SOURCE_FILE_MISSING_OR_LINK")
    size = path.stat().st_size
    if size > MAX_GLB_BYTES or size < 32 or size != expected["bytes"]:
        raise ValueError("SOURCE_SIZE_MISMATCH")
    data = path.read_bytes()
    digest = _sha256(data)
    if digest != expected["source_sha256"]:
        raise ValueError("SOURCE_SHA256_MISMATCH")
    magic, version, total = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2 or total != len(data):
        raise ValueError("GLB_HEADER_INVALID")
    offset = 12
    chunks = []
    while offset < len(data):
        if offset+8 > len(data):
            raise ValueError("GLB_CHUNK_TRUNCATED")
        length, name = struct.unpack_from("<I4s", data, offset)
        offset += 8
        if length % 4 or length > MAX_GLB_BYTES or offset+length > len(data):
            raise ValueError("GLB_CHUNK_LENGTH_INVALID")
        chunks.append((name, data[offset:offset+length]))
        offset += length
    if len(chunks) != 2 or chunks[0][0] != b"JSON" or chunks[1][0] != b"BIN\x00":
        raise ValueError("GLB_CHUNKS_UNSUPPORTED")
    if len(chunks[0][1]) > 131_072:
        raise ValueError("GLB_JSON_TOO_LARGE")
    doc = json.loads(chunks[0][1].decode("utf-8"))
    binary = chunks[1][1]
    if doc.get("asset", {}).get("version") != "2.0":
        raise ValueError("GLTF_VERSION_INVALID")
    buffers = doc.get("buffers", [])
    if len(buffers) != 1 or buffers[0].get("uri") is not None or buffers[0].get("byteLength", 0) > len(binary):
        raise ValueError("EXTERNAL_BUFFER_UNSUPPORTED")
    if (len(doc.get("nodes", [])) > 128 or len(doc.get("meshes", [])) > 32 or
        len(doc.get("accessors", [])) > 128 or len(doc.get("bufferViews", [])) > 128):
        raise ValueError("SCENE_COMPLEXITY_LIMIT")
    if (len(doc.get("meshes", [])) != expected["meshes"] or
        len(doc.get("materials", [])) != expected["materials"] or
        len(doc.get("images", [])) != expected["images"]):
        raise ValueError("SCENE_METADATA_MISMATCH")
    scene_idx = doc.get("scene", 0)
    scenes = doc.get("scenes", [])
    if type(scene_idx) is not int or not 0 <= scene_idx < len(scenes):
        raise ValueError("SCENE_INDEX_INVALID")
    nodes = doc.get("nodes", [])
    all_vertices, all_faces = [], []
    vertex_count = 0
    def walk(node_idx, parent, active, depth=0):
        nonlocal vertex_count
        if depth > 8 or type(node_idx) is not int or not 0 <= node_idx < len(nodes) or node_idx in active:
            raise ValueError("SCENE_GRAPH_INVALID")
        node = nodes[node_idx]
        transform = parent @ _node_matrix(node)
        if "mesh" in node:
            mesh_idx = node["mesh"]
            meshes = doc["meshes"]
            if type(mesh_idx) is not int or not 0 <= mesh_idx < len(meshes):
                raise ValueError("MESH_INDEX_INVALID")
            for primitive in meshes[mesh_idx].get("primitives", []):
                if primitive.get("mode", 4) != 4 or "indices" not in primitive:
                    raise ValueError("PRIMITIVE_MODE_UNSUPPORTED")
                p_idx = primitive.get("attributes", {}).get("POSITION")
                xyz = _read_accessor(doc, binary, p_idx, "VEC3")
                indices = _read_accessor(doc, binary, primitive["indices"], "SCALAR").reshape(-1)
                if len(indices) % 3 or np.max(indices) >= len(xyz):
                    raise ValueError("INDICES_INVALID")
                if not np.isfinite(xyz).all():
                    raise ValueError("VERTICES_NONFINITE")
                homo = np.concatenate([xyz.astype(np.float64),
                                       np.ones((len(xyz),1))], axis=1)
                world = (transform @ homo.T).T
                if not np.isfinite(world).all() or np.any(np.abs(world[:,3]) < 1e-9):
                    raise ValueError("VERTEX_TRANSFORM_INVALID")
                pos = (world[:,:3] / world[:,3,None]).astype(np.float32)
                faces = indices.reshape(-1,3).astype(np.int32)
                all_vertices.append(pos)
                all_faces.append(faces + vertex_count)
                vertex_count += len(pos)
        for child in node.get("children", []):
            walk(child, transform, active | {node_idx}, depth+1)

    for root_node in scenes[scene_idx].get("nodes", []):
        walk(root_node, np.eye(4, dtype=np.float64), set())
    if not all_faces:
        raise ValueError("NO_SUPPORTED_TRIANGLE_GEOMETRY")
    vertices = np.concatenate(all_vertices)
    faces = np.concatenate(all_faces)
    if len(vertices) > MAX_VERTICES or len(faces) > MAX_TRIANGLES:
        raise ValueError("MESH_TOO_LARGE")
    if len(vertices) != expected["vertices"] or len(faces) != expected["triangles"]:
        raise ValueError("LOD_GEOMETRY_COUNT_MISMATCH")
    return vertices, faces, digest


def _camera_transform(vertices, config):
    yaw = np.deg2rad(_clean_number(config["yaw_degrees"], -180, 180))
    pitch = np.deg2rad(_clean_number(config["pitch_degrees"], -85, 85))
    cy = _clean_number(config["center_y"], -100, 100)
    span_x = _clean_number(config["x_half_extent"], .001, 200)
    span_y = _clean_number(config["y_half_extent"], .001, 200)
    x, y, z = vertices.T
    rx = np.cos(yaw)*x - np.sin(yaw)*z
    rz = np.sin(yaw)*x + np.cos(yaw)*z
    ry = np.cos(pitch)*(y-cy) - np.sin(pitch)*rz
    depth = np.sin(pitch)*(y-cy) + np.cos(pitch)*rz
    homogeneous = np.stack((rx/span_x, ry/span_y, depth, np.ones(len(vertices))),
                           axis=1).astype(np.float32)
    if not np.isfinite(homogeneous).all() or np.max(np.abs(homogeneous)) > 1e4:
        raise ValueError("CAMERA_PROJECTED_NONFINITE")
    return homogeneous


class _FlatShader:
    def vertex_shader(self, vertex):
        return vertex.position, {"color": vertex.color}

    def fragment_shader(self, varyings):
        rgb = np.clip(np.asarray(varyings["color"]) * 255, 0, 255).astype(np.uint8)
        return int(rgb[0]), int(rgb[1]), int(rgb[2]), 255


def render_lod(path: Path, entry: dict, camera: dict, out: Path, pixels=192, repeats=2):
    from software_gpu.graphics.framebuffer import Framebuffer
    from software_gpu.graphics.rasterizer import SoftwareRasterizer
    from software_gpu.graphics.shader import Vertex

    vertices, faces, digest = load_glb(path, entry)
    clip = _camera_transform(vertices, camera)
    # Mesh material is marked doubleSided. For orthographic geometry-only
    # inspection orient each triangle toward the camera once. No extra faces.
    screens = clip[:,:2]
    ab = screens[faces[:,1]]-screens[faces[:,0]]
    ac = screens[faces[:,2]]-screens[faces[:,0]]
    orient = ab[:,0]*ac[:,1]-ab[:,1]*ac[:,0]
    faces = faces.copy()
    back = orient < 0
    faces[back,1], faces[back,2] = faces[back,2].copy(), faces[back,1].copy()
    shader = _FlatShader()
    color = np.asarray([.80,.70,.45], dtype=np.float32)
    mesh = [Vertex(v, color=color) for v in clip]
    fb = Framebuffer(pixels, pixels)
    render = SoftwareRasterizer(fb, backend="tiles", num_threads=1, tile_size=16)
    samples = []
    digests = []
    covered = []
    try:
        for _ in range(repeats):
            fb.clear(16,25,38,255, depth=1.0)
            t0 = time.perf_counter_ns()
            c0 = time.process_time_ns()
            render.draw_mesh(mesh, [tuple(int(i) for i in f) for f in faces], shader)
            samples.append({"wall_ms": round((time.perf_counter_ns()-t0)/1e6,3),
                            "cpu_ms": round((time.process_time_ns()-c0)/1e6,3)})
            digests.append(_sha256(fb.color_buffer.tobytes()+fb.depth_buffer.tobytes()))
            covered.append(int(np.count_nonzero(fb.depth_buffer < 1.0)))
        if len(set(digests)) != 1 or max(covered) <= 0:
            raise ValueError("REPLAY_IMAGE_HASH_MISMATCH_OR_EMPTY")
        out.mkdir(parents=True, exist_ok=True)
        image_path = out / ("Aurion_Street_Lamp_LOD%d_ARE.bmp" % entry["lod"])
        fb.save_bmp(str(image_path))
        image_sha = _sha256(image_path.read_bytes())
    finally:
        render.executor.shutdown(wait=True)
    import statistics
    return {
        "lod": entry["lod"], "source_sha256": digest,
        "source_bytes": entry["bytes"], "vertices": len(vertices),
        "triangles": len(faces), "pixels": pixels, "repeats": repeats,
        "replay_hash_sha256": digests[0], "repeat_byte_identical": True,
        "covered_pixels": covered[0],
        "median_wall_ms": round(statistics.median(x["wall_ms"] for x in samples),3),
        "samples": samples, "image_bmp_sha256": image_sha,
        "image_file": image_path.name, "pipeline": "ARE tiles CPU / flat color / geometry only",
        "texture_pbr_equivalence": False,
    }


def _child_run(path, entry, camera, output, pixels, repeats, q, memory_bytes):
    try:
        if sys.platform.startswith("linux"):
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        record = render_lod(path, entry, camera, output, pixels, repeats)
        q.put({"ok": record})
    except BaseException as exc:
        q.put({"error": type(exc).__name__, "family": str(exc)[:90]})


def run_isolated(path, entry, camera, output, pixels=192, repeats=2,
                 timeout=65, memory_mb=4096):
    if type(pixels) is not int or not 32 <= pixels <= 256:
        raise ValueError("PIXEL_BUDGET_INVALID")
    if type(repeats) is not int or not 2 <= repeats <= 5:
        raise ValueError("REPEAT_BUDGET_INVALID")
    if not .001 <= timeout <= 120 or not 512 <= memory_mb <= 4096:
        raise ValueError("RESOURCE_BUDGET_INVALID")
    context = mp.get_context("spawn")
    q = context.Queue(maxsize=1)
    proc = context.Process(target=_child_run, args=(
        path, entry, camera, output, pixels, repeats, q, memory_mb*1024**2
    ))
    proc.start()
    try:
        try:
            reply = q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("AURION_OFFLINE_DEADLINE_EXCEEDED") from None
        if "ok" not in reply:
            raise ValueError("AURION_OFFLINE_WORKER_FAILED:"+reply.get("error", "UNKNOWN"))
        return reply["ok"]
    finally:
        if proc.is_alive():
            proc.terminate()
        proc.join(timeout=2)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=2)
        q.close()
        q.join_thread()


def read_manifest(path: Path):
    doc = json.loads(path.read_text("utf-8"))
    if doc.get("protocol") != PROTOCOL or doc.get("authority") != "offline-read-only":
        raise ValueError("MANIFEST_PROTOCOL_OR_AUTHORITY_INVALID")
    entries = doc.get("lods", [])
    if not isinstance(entries, list) or not 1 <= len(entries) <= 4:
        raise ValueError("LOD_MANIFEST_SIZE_INVALID")
    for entry in entries:
        if (type(entry.get("lod")) is not int or
            entry.get("file") != "Aurion_Street_Lamp_LOD%d.glb" % entry["lod"] or
            type(entry.get("bytes")) is not int or
            not 32 <= entry["bytes"] <= MAX_GLB_BYTES or
            not isinstance(entry.get("source_sha256"), str) or
            len(entry["source_sha256"]) != 64):
            raise ValueError("LOD_MANIFEST_INVALID")
    if len({x["lod"] for x in entries}) != len(entries):
        raise ValueError("LOD_MANIFEST_DUPLICATE")
    return doc


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[3] /
                   "fixtures/aurion/street_lamp/manifest.json")
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--pixels", type=int, default=192)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--timeout", type=float, default=65)
    p.add_argument("--memory-mb", type=int, default=4096)
    args = p.parse_args()
    data = read_manifest(args.manifest)
    if not args.model_dir.is_dir() or args.model_dir.is_symlink():
        p.error("MODEL_DIRECTORY_UNAVAILABLE")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = []
    try:
        for entry in data["lods"]:
            result.append(run_isolated(args.model_dir / entry["file"], entry,
                                       data["camera"], args.output_dir,
                                       args.pixels, args.repeats, args.timeout, args.memory_mb))
    except (ValueError, TimeoutError) as exc:
        print("AURION_FIXTURE_FAIL "+str(exc).split(":")[0], file=sys.stderr)
        raise SystemExit(2)
    body = {
        "protocol": RECEIPT_PROTOCOL, "authority": "offline-read-only",
        "input_manifest_sha256": _sha256(args.manifest.read_bytes()),
        "repo_revision": os.environ.get("GITHUB_SHA", "local"),
        "python": platform.python_version(), "os": platform.platform(),
        "backend": "ARE tiles CPU", "gpu_required": False,
        "pbr_or_aurion_renderer_equivalence": "NOT_ESTABLISHED",
        "outcomes": result,
    }
    receipt_content = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    body["receipt_sha256"] = _sha256(receipt_content)
    path = args.output_dir / "aurion-lod-receipt.json"
    path.write_text(json.dumps(body, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print("AURION_OFFLINE_GLBS_OK "+body["receipt_sha256"])


if __name__ == "__main__":
    main()
