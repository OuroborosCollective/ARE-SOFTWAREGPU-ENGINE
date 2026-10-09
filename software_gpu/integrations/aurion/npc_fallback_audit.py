"""Read-only SHA-pinned NPC glTF skin/animation/attachment verifier.

This inspects actual GLB binary accessors, not merely metadata. It does NOT
perform complete skinned mesh rendering or replace Aurion's NPC animation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

import numpy as np

MANIFEST_PROTOCOL = "are.aurion.npc-fallback-fixtures.v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 1_048_576
EXPECTED_ANIMATIONS = ("Attack 2", "Cast Spell", "Death", "Fight", "Idle", "Run", "Walk")
SLOTS = ("Slot_Hand_L", "Slot_Shield", "Slot_Shoulder_L", "Slot_Hand_R",
         "Slot_MainHand", "Slot_Shoulder_R", "Slot_Chest", "Slot_Head", "Slot_Legs")
TYPES = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
DTYPES = {5121: "<u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
NAME = re.compile(r"[A-Za-z0-9_]{1,80}\Z")


def _fail(code):
    raise ValueError(code)


def read_manifest(path: Path):
    if path.stat().st_size > 65536:
        _fail("MANIFEST_OVERSIZE")
    data = json.loads(path.read_text("utf-8"))
    if data.get("protocol") != MANIFEST_PROTOCOL or data.get("authority") != "offline-read-only":
        _fail("MANIFEST_PROTOCOL_INVALID")
    families = data.get("families")
    if not isinstance(families, list) or len(families) != 5:
        _fail("FAMILY_COUNT_INVALID")
    if len({f["name"] for f in families}) != 5:
        _fail("FAMILY_DUPLICATE")
    for family in families:
        if not NAME.fullmatch(family["name"]) or [x["lod"] for x in family["lods"]] != [0, 1]:
            _fail("LOD_PAIR_INVALID")
        for entry in family["lods"]:
            if (not entry["file"].startswith(family["name"] + "_LOD" + str(entry["lod"]))
                or not entry["file"].endswith(".glb")
                or "/" in entry["file"] or chr(92) in entry["file"]
                or not 32 <= entry["bytes"] <= MAX_BYTES
                or not re.fullmatch("[0-9a-f]{64}", entry["sha256"])):
                _fail("MANIFEST_FILE_INVALID")
    return data


def load_original(path: Path, entry):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["bytes"]:
        _fail("SOURCE_SIZE_OR_FILE_INVALID")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        _fail("SOURCE_HASH_MISMATCH")
    if len(raw) < 28 or struct.unpack_from("<4sII", raw) != (b"glTF", 2, len(raw)):
        _fail("GLB_HEADER_INVALID")
    offset = 12
    chunks = []
    while offset < len(raw):
        if offset + 8 > len(raw):
            _fail("GLB_CHUNK_INVALID")
        length, typ = struct.unpack_from("<I4s", raw, offset)
        offset += 8
        if length % 4 or offset + length > len(raw):
            _fail("GLB_CHUNK_INVALID")
        chunks.append((typ, raw[offset:offset+length]))
        offset += length
    if len(chunks) != 2 or chunks[0][0] != b"JSON" or chunks[1][0] != b"BIN\x00":
        _fail("GLB_CHUNKS_INVALID")
    if len(chunks[0][1]) > MAX_JSON_BYTES:
        _fail("GLB_JSON_LIMIT")
    doc = json.loads(chunks[0][1])
    if doc.get("asset", {}).get("version") != "2.0" or doc.get("extensionsRequired"):
        _fail("GLTF_EXTENSION_UNSUPPORTED")
    if len(doc.get("buffers", [])) != 1 or doc["buffers"][0].get("uri") is not None:
        _fail("EXTERNAL_BUFFER_UNSUPPORTED")
    if doc["buffers"][0]["byteLength"] > len(chunks[1][1]):
        _fail("BUFFER_LENGTH_INVALID")
    return doc, chunks[1][1]


def accessor(doc, binary, index):
    accessors = doc["accessors"]
    if type(index) is not int or not 0 <= index < len(accessors):
        _fail("ACCESSOR_INDEX_INVALID")
    a = accessors[index]
    if "sparse" in a or a.get("normalized", False) and a["componentType"] == 5126:
        _fail("ACCESSOR_ENCODING_UNSUPPORTED")
    t = a.get("type")
    dtype = np.dtype(DTYPES[a["componentType"]])
    ncomp = TYPES[t]
    count = a["count"]
    if type(count) is not int or not 1 <= count <= 100_000:
        _fail("ACCESSOR_COUNT_INVALID")
    view = doc["bufferViews"][a["bufferView"]]
    stride = view.get("byteStride", dtype.itemsize*ncomp)
    offset = view.get("byteOffset", 0)
    inner = a.get("byteOffset", 0)
    length = view["byteLength"]
    if (any(type(v) is not int for v in (stride, offset, inner, length))
        or stride < dtype.itemsize*ncomp or stride > 256
        or offset < 0 or inner < 0 or length < 0
        or inner+(count-1)*stride+ncomp*dtype.itemsize > length
        or offset+length > len(binary)):
        _fail("ACCESSOR_BOUNDS_INVALID")
    return np.ndarray((count,ncomp),dtype=dtype,buffer=binary,
                      offset=offset+inner,strides=(stride,dtype.itemsize)).copy()


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def inspect_original(path: Path, entry: dict, family: dict):
    doc, binary = load_original(path, entry)
    nodes = doc.get("nodes", [])
    skins = doc.get("skins", [])
    clips = doc.get("animations", [])
    if len(skins) != 1 or len(skins[0]["joints"]) != 65 or len(clips) != 7 or len(nodes) > 256:
        _fail("RIG_OR_ANIMATIONS_MISSING")
    joints = skins[0]["joints"]
    if len(set(joints)) != 65 or any(type(i) is not int or i < 0 or i >= len(nodes) for i in joints):
        _fail("JOINT_INDEX_INVALID")
    if "inverseBindMatrices" not in skins[0]:
        _fail("INVERSE_BIND_MISSING")
    matrices = accessor(doc, binary, skins[0]["inverseBindMatrices"])
    if matrices.shape != (65,16) or not np.isfinite(matrices).all():
        _fail("INVERSE_BIND_INVALID")
    for node in nodes:
        if "skin" in node and node["skin"] != 0:
            _fail("MESH_SKIN_INVALID")
    parents = [(i,child) for i,node in enumerate(nodes) for child in node.get("children",[])]
    if any(type(ch) is not int or ch < 0 or ch >= len(nodes) for _,ch in parents):
        _fail("NODE_TREE_INVALID")
    actual_slots = [node["name"] for node in nodes if node.get("name","").startswith("Slot_")]
    if family["explicit_equipment_slots"]:
        if sorted(actual_slots) != sorted(SLOTS):
            _fail("EQUIPMENT_SLOTS_INVALID")
        by_name={n.get("name"):n for n in nodes}
        parents_by_child={ch:i for i,ch in parents}
        for idx,node in enumerate(nodes):
            if node.get("name") not in SLOTS:
                continue
            extra=node.get("extras", {})
            if extra.get("equipment_slot") != node["name"]:
                _fail("EQUIPMENT_SLOT_METADATA_INVALID")
            par=parents_by_child.get(idx)
            if par is None or nodes[par].get("name") != extra.get("attachment_bone"):
                _fail("EQUIPMENT_BONE_PARENT_MISMATCH")
    elif actual_slots:
        _fail("UNEXPECTED_EQUIPMENT_SLOT")
    animations=[]
    for anim in clips:
        channels=[]
        if len(anim["channels"]) != 195:
            _fail("ANIMATION_CHANNEL_COUNT_INVALID")
        for ch in anim["channels"]:
            samp=anim["samplers"][ch["sampler"]]
            target=ch["target"]
            times=accessor(doc,binary,samp["input"])
            values=accessor(doc,binary,samp["output"])
            if (times.shape[1] != 1 or values.shape[0] != len(times)
                or not np.isfinite(times).all() or not np.isfinite(values).all()
                or np.any(np.diff(times[:,0]) <= 0)
                or samp.get("interpolation", "LINEAR") not in ("STEP", "LINEAR")
                or target["path"] not in ("translation","rotation","scale")
                or target["node"] not in joints):
                _fail("ANIMATION_SAMPLER_INVALID")
            expected_dimensions=4 if target["path"]=="rotation" else 3
            if values.shape[1] != expected_dimensions:
                _fail("ANIMATION_VALUE_SHAPE_INVALID")
            channels.append((target["node"], target["path"], samp.get("interpolation","LINEAR"),
                             hashlib.sha256(times.tobytes()).hexdigest(),
                             hashlib.sha256(values.tobytes()).hexdigest()))
        animations.append({"name":anim["name"],"channels":channels})
    if sorted(a["name"] for a in animations) != sorted(EXPECTED_ANIMATIONS):
        _fail("ANIMATION_NAMES_INVALID")
    triangles=0; vertices=0; weighted_count=0; max_weight_error=0.0
    for mesh in doc.get("meshes",[]):
        for prim in mesh.get("primitives",[]):
            attrs=prim.get("attributes",{})
            if prim.get("mode",4) != 4 or "POSITION" not in attrs or "indices" not in prim:
                _fail("MESH_MODE_UNSUPPORTED")
            xyz=accessor(doc,binary,attrs["POSITION"])
            idx=accessor(doc,binary,prim["indices"])
            if not np.isfinite(xyz).all() or xyz.shape[1]!=3 or len(idx)%3 or idx.max()>=len(xyz):
                _fail("MESH_TRIANGLES_INVALID")
            triangles+=len(idx)//3
            vertices+=len(xyz)
            if "JOINTS_0" in attrs or "WEIGHTS_0" in attrs:
                if "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
                    _fail("SKINNING_ATTRIBUTES_INCOMPLETE")
                j=accessor(doc,binary,attrs["JOINTS_0"])
                w=accessor(doc,binary,attrs["WEIGHTS_0"])
                if (j.shape != (len(xyz),4) or w.shape != (len(xyz),4)
                    or j.max()>=len(joints) or not np.isfinite(w).all()
                    or np.any(w < 0) or np.any(w > 1)):
                    _fail("WEIGHTS_OR_INDICES_INVALID")
                err=float(np.abs(w.sum(axis=1)-1).max())
                if err > 1e-4:
                    _fail("SKIN_WEIGHTS_NOT_NORMALIZED")
                max_weight_error=max(max_weight_error,err)
                weighted_count+=1
    if (triangles != entry["triangles"] or vertices != entry["vertices"]
        or len(doc.get("meshes",[])) != family["meshes"]
        or len(nodes) != family["nodes"] or len(doc.get("materials",[]))!=family["materials"]
        or len(doc.get("images",[]))!=family["images"]
        or weighted_count < 1):
        _fail("MODEL_METADATA_MISMATCH")
    clip_hash=_digest(animations)
    rig={"joint_names":[nodes[i].get("name") for i in joints],
         "node_names":[x.get("name") for x in nodes],
         "skins":[x.get("name") for x in skins],
         "parents":parents,
         "inverse_bind":hashlib.sha256(matrices.tobytes()).hexdigest()}
    if clip_hash != family["animation_stream_sha256"] or _digest(rig)!=family["rig_structure_sha256"]:
        _fail("RIG_ANIMATION_STREAM_HASH_MISMATCH")
    return {"file":entry["file"],"lod":entry["lod"],"sha256":entry["sha256"],
            "triangles":triangles,"vertices":vertices,"joints":len(joints),
            "clips":len(animations),"channels_per_clip":195,
            "skin_weight_max_error":round(max_weight_error,9),
            "explicit_equipment_slots":actual_slots,
            "animation_stream_sha256":clip_hash,
            "rig_structure_sha256":_digest(rig),
            "runtime_skinned_rendering":"NOT_TESTED",
            "authority":"offline-read-only"}


def verify_all(manifest_path: Path, source_dir: Path):
    data=read_manifest(manifest_path)
    entries=[]
    for family in data["families"]:
        results=[inspect_original(source_dir/entry["file"],entry,family)
                 for entry in family["lods"]]
        if results[0]["rig_structure_sha256"]!=results[1]["rig_structure_sha256"] or (
            results[0]["animation_stream_sha256"]!=results[1]["animation_stream_sha256"]):
            _fail("CROSS_LOD_ANIMATION_PARITY_FAILED")
        entries.extend(results)
    result={"protocol":MANIFEST_PROTOCOL,"authority":"offline-read-only",
            "source_manifest_sha256":hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "validated_count":len(entries),"results":entries,
            "world_state_writes":False,"originals_loaded":True}
    result["receipt_sha256"]=_digest(result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,default=Path(__file__).resolve().parents[3]/
                        "fixtures/aurion/npc_fallback/manifest.json")
    parser.add_argument("--source-dir",type=Path,required=True)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    receipt=verify_all(args.manifest,args.source_dir)
    body=json.dumps(receipt,sort_keys=True,indent=2)+"\n"
    if args.output:
        args.output.write_text(body,encoding="utf-8")
    print(body)


if __name__=="__main__":
    main()
