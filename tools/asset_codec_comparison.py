"""SHA-bound, opt-in GLB codec research for Issue #294.

No codec decoder or importer is installed by this module. Never treat GLB
container inspection as decode, animation, native import, or full-frame proof.
All functions are offline; unsupported paths are explicit and fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct

import numpy as np

PROTOCOL = "are.asset-codec-comparison.v1"
INPUT_PROTOCOL = "are.asset-codec-inputs.v1"
SOURCE_REVISION = "e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea"
MAX_GLB_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ELEMENTS = 8_000_000
KNOWN_CODECS = {
    "KHR_draco_mesh_compression": "draco",
    "EXT_meshopt_compression": "meshopt",
}
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def require(condition, reason):
    if not condition:
        raise ValueError("ASSET_CODEC_" + reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pairs_unique(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, "DUPLICATE_JSON_KEY")
        obj[key] = value
    return obj


def _bounded_tree(obj):
    todo = [(obj, 0)]
    visit = 0
    while todo:
        value, depth = todo.pop()
        visit += 1
        require(visit <= 2_000_000 and depth <= 64, "JSON_BUDGET")
        if isinstance(value, dict):
            todo.extend((v, depth + 1) for v in value.values())
        elif isinstance(value, list):
            todo.extend((v, depth + 1) for v in value)


def _urls_rejected(obj):
    todo = [obj]
    while todo:
        value = todo.pop()
        if isinstance(value, dict):
            require(not any(k == "uri" for k in value), "EXTERNAL_RESOURCE_UNSUPPORTED")
            todo.extend(value.values())
        elif isinstance(value, list):
            todo.extend(value)


def admit_container(raw: bytes) -> dict:
    """Safe bounded inspection, never a decompress or glTF validation claim."""
    require(isinstance(raw, bytes) and 20 <= len(raw) <= MAX_GLB_BYTES, "BYTE_BUDGET")
    require(raw[:4] == b"glTF", "MAGIC")
    version, total = struct.unpack_from("<II", raw, 4)
    require(version == 2 and total == len(raw), "HEADER")
    offset, chunks = 12, []
    while offset < len(raw):
        require(offset + 8 <= len(raw), "TRUNCATED")
        size, kind = struct.unpack_from("<I4s", raw, offset)
        offset += 8
        require(size > 0 and size % 4 == 0 and size <= len(raw) - offset
                and len(chunks) < 2, "CHUNK_BOUNDS")
        chunks.append((kind, memoryview(raw)[offset:offset + size]))
        offset += size
    require(len(chunks) in (1, 2) and chunks[0][0] == b"JSON"
            and (len(chunks) == 1 or chunks[1][0] == b"BIN\x00"), "CHUNK_LAYOUT")
    require(len(chunks[0][1]) <= MAX_JSON_BYTES, "JSON_BUDGET")
    try:
        doc = json.loads(bytes(chunks[0][1]), object_pairs_hook=pairs_unique,
                         parse_constant=lambda _: require(False, "NONFINITE_JSON"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("ASSET_CODEC_INVALID_JSON") from exc
    require(isinstance(doc, dict), "JSON_OBJECT")
    _bounded_tree(doc)
    require(isinstance(doc.get("asset"), dict)
            and doc["asset"].get("version") == "2.0", "GLTF_VERSION")
    _urls_rejected(doc)
    for key in ("meshes", "accessors", "bufferViews", "animations", "skins",
                "nodes", "images", "materials", "buffers"):
        values = doc.get(key, [])
        require(type(values) is list and len(values) <= MAX_ELEMENTS, "ELEMENT_BUDGET")
    buffers = doc.get("buffers", [])
    require(len(buffers) <= 1 and (len(buffers) == 0) == (len(chunks) == 1),
            "BUFFER_LAYOUT")
    if buffers:
        require(isinstance(buffers[0], dict), "BUFFER_LAYOUT")
        size = buffers[0].get("byteLength")
        require(type(size) is int and 1 <= size <= MAX_GLB_BYTES, "BUFFER_LENGTH")
        require(size <= len(chunks[1][1]) <= size + 3, "BUFFER_LENGTH")
    for view in doc.get("bufferViews", []):
        require(isinstance(view, dict), "VIEW")
        for key in ("byteLength", "byteOffset", "byteStride"):
            if key in view:
                require(type(view[key]) is int and 0 <= view[key] <= MAX_GLB_BYTES,
                        "VIEW_BOUNDS")
        if "byteOffset" in view and "byteLength" in view and buffers:
            require(view["byteOffset"] + view["byteLength"] <= buffers[0]["byteLength"],
                    "VIEW_BOUNDS")
    for accessor in doc.get("accessors", []):
        require(isinstance(accessor, dict), "ACCESSOR")
        count = accessor.get("count")
        require(type(count) is int and 1 <= count <= MAX_ELEMENTS,
                "ACCESSOR_COUNT")
    required = doc.get("extensionsRequired", [])
    used = doc.get("extensionsUsed", [])
    require(type(required) is list and type(used) is list
            and all(type(x) is str and 0 < len(x) <= 128 for x in required + used),
            "EXTENSION_DECLARATIONS")
    discovered = set()
    for mesh in doc.get("meshes", []):
        require(isinstance(mesh, dict), "MESH")
        for primitive in mesh.get("primitives", []):
            require(isinstance(primitive, dict), "PRIMITIVE")
            if "KHR_draco_mesh_compression" in primitive.get("extensions", {}):
                discovered.add("draco")
    for view in doc.get("bufferViews", []):
        if "EXT_meshopt_compression" in view.get("extensions", {}):
            discovered.add("meshopt")
    for ext in used + required:
        if ext in KNOWN_CODECS:
            discovered.add(KNOWN_CODECS[ext])
    codec = next(iter(discovered)) if len(discovered) == 1 else (
        "none" if not discovered else "mixed")
    morph = sum(len(p.get("targets", [])) for m in doc.get("meshes", [])
                for p in m.get("primitives", []))
    require(morph <= MAX_ELEMENTS, "MORPH_BUDGET")
    other_required = sorted(set(required) - set(KNOWN_CODECS))
    # Does not mark an ordinary GLB 'tested': native import remains independent.
    native_status = ("unsupported" if codec != "none" or morph or other_required
                     else "unverified")
    return {
        "sha256": sha(raw), "bytes": len(raw), "codec": codec,
        "native_status": native_status,
        "unsupported_extensions": other_required,
        "skins": len(doc.get("skins", [])), "animations": len(doc.get("animations", [])),
        "morph_targets": morph, "meshes": len(doc.get("meshes", [])),
        "material_identity_sha256": sha(json.dumps(doc.get("materials", []),
                                                  sort_keys=True,
                                                  separators=(",", ":")).encode()),
        "rig_identity_sha256": sha(json.dumps({
            "skins": doc.get("skins", []), "nodes": doc.get("nodes", []),
            "animations": doc.get("animations", [])}, sort_keys=True,
            separators=(",", ":")).encode()),
        "source_geometry_sha256": sha(json.dumps({
            "meshes": doc.get("meshes", []),
            "accessors": doc.get("accessors", []),
            "bufferViews": doc.get("bufferViews", [])}, sort_keys=True,
            separators=(",", ":")).encode()),
    }


def validate_manifest(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs_unique)
    require(type(data) is dict and data.get("protocol") == INPUT_PROTOCOL
            and data.get("source_repository") == "KhronosGroup/glTF-Sample-Assets"
            and data.get("source_revision") == SOURCE_REVISION, "INPUT_MANIFEST")
    assets = data.get("assets")
    require(type(assets) is list and 6 <= len(assets) <= 20, "INPUT_ASSETS")
    names = set()
    for asset in assets:
        require(type(asset) is dict and
                set(("id", "class", "file", "bytes", "sha256", "license",
                     "attribution", "source_url", "license_url")) <= set(asset),
                "INPUT_ASSET_RECORD")
        name = asset["file"]
        require(type(name) is str and re.fullmatch(r"[A-Za-z0-9_-]+\.glb", name)
                and name not in names, "INPUT_NAME")
        names.add(name)
        require(asset["class"] in ("static", "rig", "morph"), "INPUT_CLASS")
        require(type(asset["bytes"]) is int and 20 <= asset["bytes"] <= MAX_GLB_BYTES,
                "INPUT_SIZE")
        require(type(asset["sha256"]) is str and DIGEST.fullmatch(asset["sha256"]),
                "INPUT_SHA")
        require(type(asset["license"]) is str and asset["license"].startswith("CC-"),
                "INPUT_LICENSE")
        model = name[:-4]
        prefix = ("https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/"
                  + SOURCE_REVISION + "/Models/" + model + "/glTF-Binary/" + name)
        require(asset["source_url"] == prefix, "INPUT_SOURCE_URL")
        require(asset["license_url"] ==
                "https://github.com/KhronosGroup/glTF-Sample-Assets/blob/" +
                SOURCE_REVISION + "/Models/" + model + "/README.md",
                "INPUT_LICENSE_URL")
    return data


def verify_asset(path: Path, expected: dict) -> bytes:
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), "SOURCE_PATH")
    require(path.stat().st_size == expected["bytes"], "SOURCE_SIZE")
    raw = path.read_bytes()
    require(sha(raw) == expected["sha256"], "SOURCE_SHA")
    require(admit_container(raw)["sha256"] == expected["sha256"], "SOURCE_GLTF")
    return raw


def compare_arrays(a, b) -> dict:
    original = np.asarray(a)
    candidate = np.asarray(b)
    require(original.shape == candidate.shape and original.size <= MAX_ELEMENTS * 16
            and original.size > 0, "ATTRIBUTE_SHAPE")
    require(np.issubdtype(original.dtype, np.number)
            and np.issubdtype(candidate.dtype, np.number), "ATTRIBUTE_DTYPE")
    require(np.isfinite(original).all() and np.isfinite(candidate).all(),
            "ATTRIBUTE_NONFINITE")
    delta = np.abs(original.astype(np.float64) - candidate.astype(np.float64))
    return {"exact": bool(np.array_equal(original, candidate)),
            "max_abs": float(delta.max()),
            "mean_abs": float(delta.mean()),
            "rmse": float(np.sqrt(np.mean(delta * delta)))}


def _box_mean(a, window=7):
    """Replicate-edge box mean via integral image, no scipy dependency."""
    radius = window // 2
    pad = np.pad(a.astype(np.float64), ((radius, radius), (radius, radius)),
                 mode="edge")
    total = np.pad(pad, ((1, 0), (1, 0)), mode="constant")
    total = total.cumsum(axis=0).cumsum(axis=1)
    return (total[window:, window:] - total[:-window, window:]
            - total[window:, :-window] + total[:-window, :-window]) / (window * window)


def _ssim_7x7(a, b):
    x, y = a.astype(np.float64), b.astype(np.float64)
    values = []
    for channel in range(3):
        p = x[..., channel]
        q = y[..., channel]
        mx, my = _box_mean(p), _box_mean(q)
        xx = _box_mean(p * p) - mx * mx
        yy = _box_mean(q * q) - my * my
        xy = _box_mean(p * q) - mx * my
        c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
        ssim = ((2 * mx * my + c1) * (2 * xy + c2)) / (
            (mx * mx + my * my + c1) * (xx + yy + c2))
        values.append(float(np.mean(ssim)))
    return float(np.mean(values))


def compare_frames(base, candidate, base_depth, candidate_depth) -> dict:
    a, b = np.asarray(base), np.asarray(candidate)
    z, w = np.asarray(base_depth), np.asarray(candidate_depth)
    require(a.ndim == 3 and a.shape == b.shape and a.shape[2] == 4
            and a.dtype == b.dtype == np.dtype("uint8")
            and 1 <= a.shape[0] <= 512 and 1 <= a.shape[1] <= 512,
            "FRAME_SHAPE")
    require(z.shape == w.shape == a.shape[:2]
            and z.dtype == w.dtype == np.dtype("float32")
            and np.isfinite(z).all() and np.isfinite(w).all(), "DEPTH_SHAPE")
    diff = a[..., :3].astype(np.float64) - b[..., :3].astype(np.float64)
    mse = float(np.mean(diff * diff))
    return {
        "byte_equal": bool(np.array_equal(a, b)),
        "depth_equal": bool(np.array_equal(z, w)),
        "depth_max_abs": float(np.max(np.abs(z.astype("float64") - w.astype("float64")))),
        "psnr_db": None if mse == 0 else float(10 * math.log10(255**2 / mse)),
        "ssim_7x7": _ssim_7x7(a, b),
        "rgb_rmse": math.sqrt(mse),
    }


def quality_verdict(*, geometry_exact: bool, rig_exact: bool,
                    material_exact: bool, clip_exact: bool, frame: dict) -> bool:
    """No lossily changed frame may qualify for timing leaderboard."""
    return (geometry_exact is True and rig_exact is True and
            material_exact is True and clip_exact is True and
            frame.get("byte_equal") is True and frame.get("depth_equal") is True)


def validate_receipt(data: dict) -> bool:
    require(type(data) is dict and data.get("protocol") == PROTOCOL, "RECEIPT_PROTOCOL")
    for field in ("asset_sha256", "original_lod_sha256", "decoder_sha256",
                  "encoder_sha256", "material_sha256", "rig_sha256", "frame_sha256"):
        require(type(data.get(field)) is str and DIGEST.fullmatch(data[field]),
                "RECEIPT_HASH")
    require(type(data.get("source_revision")) is str
            and COMMIT.fullmatch(data["source_revision"]), "RECEIPT_REVISION")
    require(data.get("codec") in ("none", "draco", "meshopt")
            and type(data.get("codec_version")) is str and bool(data["codec_version"]),
            "RECEIPT_CODEC")
    require(type(data.get("comparable")) is bool and
            data.get("verdict") == ("COMPARABLE" if data["comparable"]
                                   else "NOT_COMPARABLE"), "RECEIPT_VERDICT")
    runs = data.get("raw_runs")
    require(type(runs) is list and 15 <= len(runs) <= 30, "RECEIPT_RUNS")
    for row in runs:
        require(type(row) is dict, "RECEIPT_RUN")
        for field in ("file_read_ms", "decompression_ms", "import_ms",
                      "full_frame_ms"):
            n = row.get(field)
            require(type(n) in (float, int) and math.isfinite(n) and n >= 0,
                    "RECEIPT_TIMING")
    return True


def inspect_directory(manifest: Path, asset_dir: Path, output: Path) -> dict:
    """Never classify an unexecuted decode as successful."""
    doc = validate_manifest(manifest)
    rows = []
    for asset in doc["assets"]:
        file = Path(asset_dir) / asset["file"]
        try:
            raw = verify_asset(file, asset)
            info = admit_container(raw)
            status = "unsupported" if info["native_status"] == "unsupported" else "unverified"
            rows.append({"asset": asset["id"], "sha256": asset["sha256"],
                         "status": status, "container": info,
                         "frame_status": "unverified", "comparable": False,
                         "verdict": "NOT_COMPARABLE"})
        except (ValueError, OSError) as exc:
            rows.append({"asset": asset["id"], "sha256": asset["sha256"],
                         "status": "unverified", "reason": str(exc),
                         "frame_status": "unverified", "comparable": False,
                         "verdict": "NOT_COMPARABLE"})
    result = {"protocol": PROTOCOL, "scope": "container-only-no-renderer-no-benchmark",
              "source_revision": doc["source_revision"],
              "rankings_added": 0, "rows": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False)
                      + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("evidence/asset-codec-khronos-v1.json"))
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = inspect_directory(args.manifest, args.asset_dir, args.output)
    print("ASSET_CODEC_CONTAINER_ONLY", len(report["rows"]), report["rankings_added"])


if __name__ == "__main__":
    main()
