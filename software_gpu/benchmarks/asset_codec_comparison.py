"""Issue #294: independent opt-in Draco/Meshopt GLB2 comparison, never a runtime decoder.

Inputs are SHA/size-pinned licensed GLB2 assets and glTF-Transform 4.5.1 with a
frozen npm lock. Each codec is encoded once; every full-pipeline pair genuinely
reads, decodes, imports and renders the same source using ARE's C++17 PBR probe.
Neither benchmark receipts nor test registration promote performance rankings.
Unsupported native morph/multi-mesh/assets remain explicit UNSUPPORTED.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import struct
import subprocess
import tempfile
import time
from typing import Any

import numpy as np

from software_gpu.research.model_probe import (
    accessor, build_model_probe, load_asset, read_glb, run_model, write_scene,
)

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = "are.asset-codec-comparison.v1"
CODEC_VERSION = "4.5.1"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
ALLOWED_EXTENSIONS = frozenset({
    "KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization",
})
METRICS = ("file_read_ms", "decode_ms", "import_ms", "pose_ms",
           "first_frame_ms", "warm_frame_ms", "release_ms", "native_wall_ms")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("CODEC_" + reason)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique_json(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, "JSON_DUPLICATE_KEY")
        out[key] = value
    return out


def _check_depth(obj, depth=0):
    require(depth <= 64, "JSON_DEPTH_LIMIT")
    if isinstance(obj, dict):
        require(len(obj) <= 50000, "COMPLEXITY_LIMIT")
        for v in obj.values():
            _check_depth(v, depth+1)
    elif isinstance(obj, list):
        require(len(obj) <= 50000, "COMPLEXITY_LIMIT")
        for v in obj:
            _check_depth(v, depth+1)


def inspect_glb_container(path: Path, expected_sha: str, expected_bytes: int) -> dict:
    """Reject unknown codec extensions, external URIs and unbounded payloads before exec."""
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), "SOURCE_FILE")
    require(type(expected_bytes) is int and 32 <= expected_bytes <= MAX_FILE_BYTES
            and path.stat().st_size == expected_bytes, "SOURCE_SIZE")
    raw = path.read_bytes()
    require(digest(raw) == expected_sha, "SOURCE_SHA")
    require(len(raw) >= 32 and struct.unpack_from("<4sII", raw) ==
            (b"glTF", 2, len(raw)), "GLB_HEADER")
    chunks, offset = [], 12
    while offset < len(raw):
        require(offset+8 <= len(raw) and len(chunks) < 2, "GLB_CHUNK")
        length, kind = struct.unpack_from("<I4s", raw, offset)
        offset += 8
        require(length > 0 and length % 4 == 0 and offset+length <= len(raw),
                "GLB_CHUNK")
        chunks.append((kind, memoryview(raw)[offset:offset+length]))
        offset += length
    require(len(chunks) == 2 and [c[0] for c in chunks] ==
            [b"JSON", b"BIN\x00"], "GLB_CHUNKS")
    require(len(chunks[0][1]) <= MAX_JSON_BYTES, "JSON_BUDGET")
    try:
        document = json.loads(bytes(chunks[0][1]), object_pairs_hook=_unique_json,
                              parse_constant=lambda _: require(False, "JSON_NONFINITE"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("CODEC_JSON_INVALID") from exc
    require(isinstance(document, dict), "JSON_DOCUMENT")
    _check_depth(document)
    require(document.get("asset", {}).get("version") == "2.0", "GLTF_VERSION")
    for name, limit in (("meshes", 128), ("skins", 256), ("animations", 256),
                        ("nodes", 10000), ("accessors", 30000),
                        ("bufferViews", 30000), ("materials", 10000)):
        records = document.get(name, [])
        require(isinstance(records, list) and len(records) <= limit,
                "COMPLEXITY_LIMIT")
    required = document.get("extensionsRequired", [])
    used = document.get("extensionsUsed", [])
    require(isinstance(required, list) and isinstance(used, list)
            and all(isinstance(x, str) for x in required+used), "EXTENSION_FORMAT")
    require(set(required) <= ALLOWED_EXTENSIONS, "EXTENSION_UNSUPPORTED")
    buffers = document.get("buffers", [])
    require(isinstance(buffers, list) and 1 <= len(buffers) <= 2
            and all(isinstance(b, dict) and "uri" not in b for b in buffers),
            "EXTERNAL_RESOURCE")
    declared = buffers[0].get("byteLength")
    require(type(declared) is int and 0 <= declared <= len(chunks[1][1])
            and len(chunks[1][1])-declared <= 3, "BUFFER_LENGTH")
    # EXT_meshopt_compression may declare one *virtual* fallback buffer that
    # does not occupy BIN bytes. It MUST never be treated as decoded data.
    if len(buffers) == 2:
        fallback = buffers[1]
        require("EXT_meshopt_compression" in required and
                fallback.get("extensions") == {
                    "EXT_meshopt_compression": {"fallback": True}}
                and type(fallback.get("byteLength")) is int
                and 0 <= fallback["byteLength"] <= MAX_FILE_BYTES*4,
                "VIRTUAL_BUFFER")
    for image in document.get("images", []):
        require(isinstance(image, dict) and "uri" not in image,
                "EXTERNAL_RESOURCE")
    for view in document.get("bufferViews", []):
        require(isinstance(view, dict), "BUFFER_VIEW")
        ofs, size, index = view.get("byteOffset", 0), view.get("byteLength"), view.get("buffer", 0)
        require(type(index) is int and 0 <= index < len(buffers)
                and type(ofs) is int and type(size) is int and ofs >= 0
                and size >= 0 and ofs + size <= (
                    declared if index == 0 else buffers[1]["byteLength"]), "BUFFER_VIEW")
        ext = view.get("extensions", {}).get("EXT_meshopt_compression")
        if index == 1:
            require(isinstance(ext, dict), "VIRTUAL_BUFFER")
        if ext is not None:
            require(isinstance(ext, dict) and "EXT_meshopt_compression" in required
                    and type(ext.get("buffer")) is int and ext["buffer"] == 0
                    and all(type(ext.get(k)) is int and ext[k] >= 0
                            for k in ("byteOffset", "byteLength", "byteStride", "count"))
                    and ext["byteOffset"] + ext["byteLength"] <= declared
                    and 0 < ext["byteStride"] <= 256
                    and 0 < ext["count"] <= 24_000_000
                    and ext["byteStride"] * ext["count"] <= MAX_FILE_BYTES*4,
                    "MESHOPT_PAYLOAD_BOUNDS")
    return {"sha256": expected_sha, "bytes": len(raw), "document": document,
            "bin": chunks[1][1][:declared], "required": required, "used": used}


def metadata_signature(d: dict) -> dict:
    """Semantic identity, not text/GLB-byte identity: materials, rigs, clips, morphs."""
    nodes = d.get("nodes", [])
    def name(index):
        return nodes[index].get("name", f"node-{index}") if type(index) is int and 0 <= index < len(nodes) else None
    materials = []
    for m in d.get("materials", []):
        p = m.get("pbrMetallicRoughness", {})
        materials.append({
            "name": m.get("name"), "doubleSided": m.get("doubleSided", False),
            "alphaMode": m.get("alphaMode", "OPAQUE"),
            "baseColorFactor": p.get("baseColorFactor", [1, 1, 1, 1]),
            "metallicFactor": p.get("metallicFactor", 1.0),
            "roughnessFactor": p.get("roughnessFactor", 1.0),
            "textureSlots": sorted(k for k, v in p.items() if k.endswith("Texture") and v is not None),
        })
    rig = [{
        "joints": [name(i) for i in s.get("joints", [])],
        "skeleton": name(s.get("skeleton")) if "skeleton" in s else None,
        "inverseBindMatrices": "inverseBindMatrices" in s
    } for s in d.get("skins", [])]
    clips = []
    for animation in d.get("animations", []):
        samplers = animation.get("samplers", [])
        channels = []
        for channel in animation.get("channels", []):
            target = channel.get("target", {})
            idx = channel.get("sampler")
            method = samplers[idx].get("interpolation", "LINEAR") if type(idx) is int and 0 <= idx < len(samplers) else None
            channels.append((name(target.get("node")), target.get("path"), method))
        clips.append({"name": animation.get("name"), "channels": sorted(channels, key=str)})
    morph = [[sorted(list(t.keys())) for t in p.get("targets", [])]
             for m in d.get("meshes", []) for p in m.get("primitives", [])]
    return {"materials": materials, "rig": rig, "clips": clips, "morph": morph,
            "mesh_count": len(d.get("meshes", [])), "primitive_count": len(morph)}


def geometry_error(original: np.ndarray, candidate: np.ndarray) -> dict:
    a, b = np.asarray(original), np.asarray(candidate)
    if a.shape != b.shape:
        return {"aligned": False, "original_shape": list(a.shape),
                "candidate_shape": list(b.shape), "exact": False,
                "reason": "vertex/index order or accessor shape differs"}
    require(np.isfinite(a).all() and np.isfinite(b).all(), "NONFINITE_GEOMETRY")
    difference = np.abs(a.astype(np.float64)-b.astype(np.float64))
    return {"aligned": True, "exact": bool(np.array_equal(a, b)),
            "max_abs": float(difference.max()) if difference.size else 0.,
            "rmse": float(np.sqrt(np.mean(difference*difference))) if difference.size else 0.}


def _morph_arrays(document, binary):
    result = {}
    for i, mesh in enumerate(document.get("meshes", [])):
        for j, prim in enumerate(mesh.get("primitives", [])):
            for k, target in enumerate(prim.get("targets", [])):
                for semantic, index in target.items():
                    result[f"morph[{i}:{j}:{k}].{semantic}"] = accessor(document, binary, index)
    return result


def _numeric_arrays(info):
    document, binary = info["document"], info["bin"]
    arrays = {}
    for i, mesh in enumerate(document.get("meshes", [])):
        for j, prim in enumerate(mesh.get("primitives", [])):
            for k in ("POSITION", "NORMAL", "TEXCOORD_0", "WEIGHTS_0", "WEIGHTS_1",
                      "JOINTS_0", "JOINTS_1"):
                if k in prim.get("attributes", {}):
                    arrays[f"mesh[{i}:{j}].{k}"] = accessor(document, binary, prim["attributes"][k])
    for i, skin in enumerate(document.get("skins", [])):
        if "inverseBindMatrices" in skin:
            arrays[f"skin[{i}].INVERSE_BIND"] = accessor(
                document, binary, skin["inverseBindMatrices"])
    for i, clip in enumerate(document.get("animations", [])):
        samplers = clip.get("samplers", [])
        for j, channel in enumerate(clip.get("channels", [])):
            index = channel.get("sampler")
            require(type(index) is int and 0 <= index < len(samplers),
                    "ANIMATION_SAMPLER")
            sampler = samplers[index]
            for key in ("input", "output"):
                arrays[f"animation[{i}:{j}].{key.upper()}"] = accessor(
                    document, binary, sampler[key])
    arrays.update(_morph_arrays(document, binary))
    return arrays


def geometry_report(a_info, b_info) -> dict:
    a = _numeric_arrays(a_info)
    b = _numeric_arrays(b_info)
    keys = sorted(set(a) | set(b))
    metrics = {k: geometry_error(a[k], b[k]) if k in a and k in b else
               {"aligned": False, "exact": False, "reason": "attribute missing"} for k in keys}
    limits = {"POSITION": .001, "NORMAL": .03, "TEXCOORD_0": .002,
              "WEIGHTS_0": .01, "WEIGHTS_1": .01,
              "JOINTS_0": 0., "JOINTS_1": 0.}
    permitted = True
    for key, value in metrics.items():
        typ = key.split(".")[-1]
        limit = limits.get(typ, .001)
        if not value["aligned"] or value["max_abs"] > limit:
            permitted = False
    return {"attributes": metrics, "thresholds_max_abs": limits,
            "within_thresholds": permitted}


def quality_metrics(before: np.ndarray, after: np.ndarray) -> dict:
    a, b = np.asarray(before), np.asarray(after)
    require(a.shape == b.shape and a.ndim == 3 and a.shape[2] == 4
            and a.dtype == np.uint8 and b.dtype == np.uint8, "FRAME_SHAPE")
    exact = bool(np.array_equal(a, b))
    af = a[:, :, :3].astype(np.float64)
    bf = b[:, :, :3].astype(np.float64)
    mse = float(np.mean((af-bf)**2))
    psnr = None if mse == 0 else float(10*math.log10(255**2/mse))
    # Spatial luma SSIM averaged over non-overlapping 8x8 patches (not global SSIM).
    y_a = .2126*af[:, :, 0]+.7152*af[:, :, 1]+.0722*af[:, :, 2]
    y_b = .2126*bf[:, :, 0]+.7152*bf[:, :, 1]+.0722*bf[:, :, 2]
    scores = []
    for y in range(0, a.shape[0], 8):
        for x in range(0, a.shape[1], 8):
            p, q = y_a[y:y+8, x:x+8], y_b[y:y+8, x:x+8]
            mu_p, mu_q = float(p.mean()), float(q.mean())
            vp, vq = float(p.var()), float(q.var())
            cov = float(((p-mu_p)*(q-mu_q)).mean())
            c1, c2 = (0.01*255)**2, (0.03*255)**2
            scores.append((2*mu_p*mu_q+c1)*(2*cov+c2)/
                          ((mu_p**2+mu_q**2+c1)*(vp+vq+c2)))
    return {"exact_rgba8": exact, "psnr_db": psnr,
            "ssim_y_8x8": float(np.mean(scores)), "max_abs_rgb": int(np.max(np.abs(af-bf)))}


def _stats(values):
    v = sorted(float(x) for x in values)
    require(len(v) >= 15 and all(math.isfinite(x) and x >= 0 for x in v),
            "PAIRS_INCOMPLETE")
    med = statistics.median(v)
    def pct(t):
        f = (len(v)-1)*t
        i = int(f)
        return v[i]+(v[min(i+1, len(v)-1)]-v[i])*(f-i)
    return {"n": len(v), "median": med, "p95": pct(.95), "iqr": pct(.75)-pct(.25),
            "mad": statistics.median(abs(x-med) for x in v)}


def paired_statistics(rows, repeats):
    require(type(repeats) is int and 15 <= repeats <= 30 and len(rows) == repeats
            and all(isinstance(row, dict) and all(k in row for k in METRICS)
                    and isinstance(row.get("full_frame_digest"), str)
                    and len(row["full_frame_digest"]) == 64 for row in rows),
            "PAIRS_INCOMPLETE")
    return {"n": repeats, "stages_ms": {key: _stats([r[key] for r in rows]) for key in METRICS}}


def _run_cli(executable, action, source, target):
    command = [str(executable), action, str(source), str(target)]
    start = time.perf_counter_ns()
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=120, check=False)
    require(result.returncode == 0 and target.is_file() and
            32 <= target.stat().st_size <= MAX_FILE_BYTES, "DECODER_FAILED")
    return (time.perf_counter_ns()-start)/1e6


def _native_sample(path, native_binary, directory, pixels, workers, iteration):
    sha = digest(path.read_bytes())
    start = time.perf_counter_ns()
    asset = load_asset(path, {"sha256": sha, "bytes": path.stat().st_size}, profile="pbr")
    import_ms = (time.perf_counter_ns()-start)/1e6
    clips = asset["clips"]
    frames = [0., min(clips[0]["duration"]*.5, .25)] if clips else [0., 0.]
    request = directory / f"scene-{iteration}.are"
    write_scene(request, [dict(asset=asset, clip=0 if clips else None)], frames,
                pixels=pixels, tile=16, projection="perspective", render_profile="pbr")
    start = time.perf_counter_ns()
    output = run_model(native_binary, request, workers=workers, repeats=2,
                       render_profile="pbr", timeout=180)
    native_wall_ms = (time.perf_counter_ns()-start)/1e6
    timing = output["receipt"]["baseline_frame_timings"]
    require(len(timing) == 2 and output["receipt"]["full_buffer_parity"] is True,
            "NATIVE_FRAME_RECEIPT")
    frame = np.ascontiguousarray(output["frames"])
    depth = np.ascontiguousarray(output["depth"])
    require(frame.shape == (2, pixels, pixels, 4) and
            depth.shape == (pixels, pixels), "FRAME_SHAPE")
    dig = digest(frame.tobytes()+depth.tobytes())
    result = {"import_ms": import_ms, "pose_ms": float(timing[0]["animated_pose_ms"]),
              "first_frame_ms": float(timing[0]["frame_total_ms"]),
              "warm_frame_ms": float(timing[1]["frame_total_ms"]),
              "native_wall_ms": native_wall_ms,
              "full_frame_digest": dig, "rgba8_sha256": digest(frame.tobytes()),
              "depth_float32_sha256": digest(depth.tobytes()),
              "frame": frame.copy(), "depth": depth.copy(),
              "metadata": asset["metadata"]}
    start = time.perf_counter_ns()
    del output, asset, frame, depth
    gc.collect()
    result["release_ms"] = (time.perf_counter_ns()-start)/1e6
    request.unlink(missing_ok=True)
    return result


def _rss_bytes():
    # ru_maxrss is a process-lifetime high-water mark; never stage-attributed.
    if os.name != "posix":
        return None
    import resource
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(raw * (1024 if platform.system() == "Linux" else 1))


def _mode_preflight(name, original, path):
    info = inspect_glb_container(path, digest(path.read_bytes()), path.stat().st_size)
    native = {"source_sha256": info["sha256"], "bytes": info["bytes"],
              "extensions_required": info["required"], "extensions_used": info["used"],
              "signature": metadata_signature(info["document"])}
    return info, native


def compare_assets(manifest: dict, source_dir: Path, codec_bin: Path, package_lock: Path,
                   repeats=15, pixels=64, workers=1):
    require(type(repeats) is int and 15 <= repeats <= 30, "PAIRS_INCOMPLETE")
    require(type(pixels) is int and 32 <= pixels <= 128, "PIXELS_BUDGET")
    require(type(workers) is int and workers in (1, 2, 4, 8), "WORKER_BUDGET")
    require(manifest.get("protocol") == "are.asset-codec-sources.v1"
            and isinstance(manifest.get("assets"), list)
            and manifest["assets"] and len(manifest["assets"]) <= 12, "MANIFEST")
    require(codec_bin.is_file() and package_lock.is_file(), "CODEC_TOOL_MISSING")
    version = subprocess.check_output([str(codec_bin), "--version"], text=True, timeout=15).strip()
    require(version == CODEC_VERSION, "CODEC_VERSION")
    require(digest(package_lock.read_bytes()) == manifest["toolchain"]["package_lock_sha256"],
            "PACKAGE_LOCK_SHA")
    node_modules = codec_bin.resolve().parents[3]
    decoder_paths = {
        "draco3dgltf/draco_decoder_gltf.wasm":
            node_modules / "draco3dgltf/draco_decoder_gltf.wasm",
        "meshoptimizer/meshopt_decoder.mjs":
            node_modules / "meshoptimizer/meshopt_decoder.mjs",
    }
    require(all(p.is_file() for p in decoder_paths.values()), "DECODER_MODULE_MISSING")
    assets = []
    for rec in manifest["assets"]:
        require(set(rec) == {"name", "sha256", "bytes", "source", "license",
                            "license_url", "expected_kind", "lod"}, "ASSET_RECORD")
        require(rec["name"].replace("-", "").isalnum()
                and rec["license"] and rec["license_url"].startswith("https://")
                and rec["source"].startswith("https://")
                and rec["expected_kind"] in ("static", "rig", "morph")
                and rec["lod"] == "LOD0-original", "ASSET_MANIFEST")
        path = source_dir / (rec["name"] + ".glb")
        original = inspect_glb_container(path, rec["sha256"], rec["bytes"])
        sign = metadata_signature(original["document"])
        require(bool(sign["rig"]) == (rec["expected_kind"] == "rig") or
                rec["expected_kind"] == "morph", "ASSET_KIND")
        if rec["expected_kind"] == "morph":
            require(any(any(target for target in targets) for targets in sign["morph"]),
                    "ASSET_KIND")
        assets.append((rec, path, original, sign))
    code_paths = [Path(__file__), ROOT/"software_gpu/research/model_probe.py",
                  ROOT/"software_gpu/tests/test_asset_codec_comparison.py",
                  ROOT/"native/symbolic/model_main.cpp",
                  ROOT/"native/symbolic/model_scene.hpp",
                  ROOT/"evidence/issue294-asset-codec-sources-v1.json",
                  ROOT/"tools/asset-codec-comparison-node/package-lock.json"]
    receipt = {"protocol": PROTOCOL,
               "repeats": repeats, "pixels": pixels, "workers": workers,
               "codec_source": "gltf-transform CLI; original GLB2 is not modified",
               "toolchain": {
                   "cli_version": version,
                   "cli_entry_sha256": digest(codec_bin.resolve().read_bytes()),
                   "lock_sha256": digest(package_lock.read_bytes()),
                   "decoder_modules_sha256": {key: digest(path.read_bytes())
                                              for key, path in decoder_paths.items()},
                   "node_version": subprocess.check_output(["node", "--version"], text=True).strip(),
               },
               "checkout_revision": subprocess.check_output(
                   ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "checkout_dirty": bool(subprocess.check_output(
                   ["git", "status", "--porcelain=v1"], cwd=ROOT, text=True).strip()),
               "environment": {"python": platform.python_version(),
                               "platform": platform.platform(),
                               "rss_scope": "process-lifetime peak; not stage-attributed"},
               "source_paths_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in code_paths},
               "metrics_scope": "first/warm are native after 3 warmups; native_wall includes startup",
               "quality_thresholds": {"psnr_db_min": 40., "ssim_y_8x8_min": .98,
                                      "depth_max_abs": .001},
               "ranklist_promotion": False, "assets": []}
    with tempfile.TemporaryDirectory(prefix="are-codec294-") as tmp:
        tmpdir = Path(tmp)
        native_binary = None
        for rec, source, original, original_sig in assets:
            record = {"name": rec["name"], "original_sha256": rec["sha256"],
                      "original_bytes": rec["bytes"], "original_lod": rec["lod"],
                      "lod_source_sha256": rec["sha256"],
                      "other_lod_status": "unverified: not supplied",
                      "license": rec["license"], "license_url": rec["license_url"],
                      "kind": rec["expected_kind"], "source": rec["source"],
                      "source_signature": original_sig, "variants": {}}
            variant_paths = {"none": source}
            for mode in ("draco", "meshopt"):
                encoded = tmpdir / f"{rec['name']}.{mode}.compressed.glb"
                elapsed = _run_cli(codec_bin, mode, source, encoded)
                ci = inspect_glb_container(encoded, digest(encoded.read_bytes()), encoded.stat().st_size)
                require(("KHR_draco_mesh_compression" if mode == "draco" else
                         "EXT_meshopt_compression") in ci["required"], "COMPRESSION_NOT_APPLIED")
                variant_paths[mode] = encoded
                # A real compressed-payload negative, not a synthetic successful
                # decoder: alter a true compressed BIN extent without changing
                # valid GLB framing. The actual decoder must reject it.
                if rec["name"] == "CesiumMan":
                    corrupted = bytearray(encoded.read_bytes())
                    json_length = struct.unpack_from("<I", corrupted, 12)[0]
                    binary_base = 28 + json_length
                    if mode == "draco":
                        primitive = next(p for m in ci["document"]["meshes"]
                                         for p in m["primitives"]
                                         if "KHR_draco_mesh_compression" in p.get("extensions", {}))
                        idx = primitive["extensions"]["KHR_draco_mesh_compression"]["bufferView"]
                        start = ci["document"]["bufferViews"][idx].get("byteOffset", 0)
                    else:
                        v = next(v for v in ci["document"]["bufferViews"]
                                 if "EXT_meshopt_compression" in v.get("extensions", {}))
                        start = v["extensions"]["EXT_meshopt_compression"]["byteOffset"]
                    require(binary_base + start + 16 <= len(corrupted),
                            "CORRUPT_TEST_OFFSET")
                    corrupted[binary_base+start:binary_base+start+16] = b"\xff"*16
                    altered = tmpdir / f"{rec['name']}.{mode}.negative.glb"
                    negative_out = tmpdir / f"{rec['name']}.{mode}.negative.out.glb"
                    altered.write_bytes(corrupted)
                    negative = subprocess.run(
                        [str(codec_bin), "copy", str(altered), str(negative_out)],
                        capture_output=True, timeout=60)
                    require(negative.returncode != 0 and not negative_out.exists(),
                            "CORRUPT_CODEC_ACCEPTED")
                    record.setdefault("negative_codec_tests", []).append({
                        "codec": mode, "case": "original-encoded-BIN-first-16-bytes-FF",
                        "corrupted_sha256": digest(corrupted), "decoder_rejected": True})
                record["variants"][mode] = {
                    "encoded_sha256": ci["sha256"], "encoded_bytes": ci["bytes"],
                    "encode_once_ms": elapsed, "encoded_extensions": ci["required"],
                    "decode_transform": ["copy", "dequantize"] if mode == "meshopt"
                    else ["copy"], "samples": []}
            record["variants"]["none"] = {
                "encoded_sha256": rec["sha256"], "encoded_bytes": rec["bytes"],
                "encode_once_ms": None, "encoded_extensions": [],
                "decode_transform": [], "samples": []}
            # Prove every codec decoded artifact is extension-free and retains structural meaning.
            decoded = {"none": source}
            for mode in ("draco", "meshopt"):
                interim = tmpdir / f"{rec['name']}.{mode}.interim.glb"
                final = tmpdir / f"{rec['name']}.{mode}.decoded.glb"
                _run_cli(codec_bin, "copy", variant_paths[mode], interim)
                if mode == "meshopt":
                    _run_cli(codec_bin, "dequantize", interim, final)
                else:
                    interim.replace(final)
                info, meta = _mode_preflight(mode, original, final)
                require(not info["required"], "DECODE_NOT_UNCOMPRESSED")
                record["variants"][mode]["decoded_sha256"] = info["sha256"]
                record["variants"][mode]["decoded_bytes"] = info["bytes"]
                record["variants"][mode]["material_rig_morph_identity"] = (
                    original_sig == meta["signature"])
                try:
                    geom = geometry_report(original, info)
                except (ValueError, KeyError, TypeError) as exc:
                    geom = {"within_thresholds": False,
                            "reason": "geometry accessor unsupported: "+str(exc)[:80]}
                record["variants"][mode]["geometry_quality"] = geom
                decoded[mode] = final
            record["variants"]["none"]["decoded_sha256"] = rec["sha256"]
            record["variants"]["none"]["decoded_bytes"] = rec["bytes"]
            record["variants"]["none"]["material_rig_morph_identity"] = True
            record["variants"]["none"]["geometry_quality"] = {
                "within_thresholds": True, "reference": True}
            supported = {}
            for mode, path in decoded.items():
                try:
                    data = path.read_bytes()
                    asset = load_asset(path, {"sha256": digest(data), "bytes": len(data)}, profile="pbr")
                    supported[mode] = True
                    record["variants"][mode]["native_import"] = "tested"
                    del asset
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    supported[mode] = False
                    record["variants"][mode]["native_import"] = "unsupported: "+str(exc)[:120]
                    record["variants"][mode]["status"] = "UNSUPPORTED"
                    record["variants"][mode]["comparable"] = False
            if any(supported.values()) and native_binary is None:
                native_binary, build = build_model_probe(tmpdir / "native-build")
                receipt["toolchain"]["native_build"] = build
            # Interleaving removes systematic codec ordering between measured pairs.
            # Only fully-supported modes get complete and comparable-frame measurements.
            frames = {}
            for n in range(repeats):
                modes = ("none", "draco", "meshopt")
                rotated = modes[n % 3:] + modes[:n % 3]
                for mode in rotated:
                    if not supported[mode]:
                        continue
                    encoded = variant_paths[mode]
                    start = time.perf_counter_ns()
                    read = encoded.read_bytes()
                    file_ms = (time.perf_counter_ns()-start)/1e6
                    require(digest(read) == record["variants"][mode]["encoded_sha256"],
                            "ENCODED_SHA_DRIFT")
                    if mode == "none":
                        candidate, decode_ms = source, 0.
                    else:
                        interim = tmpdir / f"{rec['name']}.{mode}.run{n}.interim.glb"
                        target = tmpdir / f"{rec['name']}.{mode}.run{n}.decoded.glb"
                        decode_ms = _run_cli(codec_bin, "copy", encoded, interim)
                        if mode == "meshopt":
                            decode_ms += _run_cli(codec_bin, "dequantize", interim, target)
                            interim.unlink(missing_ok=True)
                        else:
                            interim.replace(target)
                        candidate = target
                        result = inspect_glb_container(candidate, digest(candidate.read_bytes()),
                                                       candidate.stat().st_size)
                        require(not result["required"], "DECODE_NOT_UNCOMPRESSED")
                    obs = _native_sample(candidate, native_binary, tmpdir, pixels, workers, n)
                    if mode != "none":
                        candidate.unlink(missing_ok=True)
                    frames[(mode, n)] = (obs.pop("frame"), obs.pop("depth"))
                    obs.update(file_read_ms=file_ms, decode_ms=decode_ms,
                               effective_file_mib_s=(len(read)/(1024*1024))/(file_ms/1000)
                               if file_ms > 0 else None,
                               peak_rss_bytes_cumulative=_rss_bytes(),
                               pass_index=n, paired_order=list(rotated))
                    record["variants"][mode]["samples"].append(obs)
            for mode, value in record["variants"].items():
                if not supported[mode]:
                    continue
                samples = value["samples"]
                value["paired_timing"] = paired_statistics(samples, repeats)
                require(len({s["full_frame_digest"] for s in samples}) == 1,
                        "FRAME_NOT_REPRODUCIBLE")
                value["reference_frame_sha256"] = samples[0]["rgba8_sha256"]
                value["reference_depth_sha256"] = samples[0]["depth_float32_sha256"]
                if mode == "none":
                    value.update(comparable=True, status="TESTED_REFERENCE",
                                 quality={"exact_rgba8": True, "depth_max_abs": 0.})
                    continue
                a, ad = frames[("none", 0)] if supported["none"] else (None, None)
                b, bd = frames[(mode, 0)]
                if a is None:
                    value["status"] = "NOT_COMPARABLE"
                    value["comparable"] = False
                    value["quality"] = {"reason": "reference native frame unsupported"}
                    continue
                require(a.shape == b.shape and a.ndim == 4 and a.shape[0] == 2,
                        "FRAME_SEQUENCE_SHAPE")
                per_frame = [quality_metrics(a[j], b[j]) for j in range(a.shape[0])]
                q = {
                    "exact_rgba8": all(v["exact_rgba8"] for v in per_frame),
                    "psnr_db": min((v["psnr_db"] for v in per_frame if v["psnr_db"] is not None), default=None),
                    "ssim_y_8x8": min(v["ssim_y_8x8"] for v in per_frame),
                    "max_abs_rgb": max(v["max_abs_rgb"] for v in per_frame),
                    "per_frame": per_frame,
                }
                q["depth_max_abs"] = float(np.max(np.abs(
                    ad.astype(np.float64)-bd.astype(np.float64))))
                thresholds = receipt["quality_thresholds"]
                pass_quality = (q["psnr_db"] is None or
                                q["psnr_db"] >= thresholds["psnr_db_min"]) and (
                                    q["ssim_y_8x8"] >= thresholds["ssim_y_8x8_min"]
                                ) and q["depth_max_abs"] <= thresholds["depth_max_abs"]
                pass_geometry = value["geometry_quality"]["within_thresholds"]
                identity = value["material_rig_morph_identity"]
                value["quality"] = q
                value["comparable"] = bool(pass_quality and pass_geometry and identity)
                value["status"] = "TESTED_COMPARABLE" if value["comparable"] else "NOT_COMPARABLE"
            receipt["assets"].append(record)
    receipt["all_native_comparable"] = all(
        value.get("comparable") is True for asset in receipt["assets"]
        for value in asset["variants"].values())
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False)
    receipt["receipt_sha256"] = digest(payload.encode("utf-8"))
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--codec-bin", type=Path, required=True)
    parser.add_argument("--package-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--pixels", type=int, default=64)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    doc = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = compare_assets(doc, args.asset_dir, args.codec_bin,
                            args.package_lock, args.repeats, args.pixels, args.workers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix+".tmp")
    temp.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+"\n",
                    encoding="utf-8")
    os.replace(temp, args.output)
    print("CODEC_COMPARISON_RECEIPT", args.output, result["receipt_sha256"])


if __name__ == "__main__":
    main()

