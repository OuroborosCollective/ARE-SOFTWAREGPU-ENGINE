"""Fail-closed offline source SHA + GLB structure readback. No source mutation."""
import hashlib
import json
from pathlib import Path
import struct

def verify(path, entry):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["bytes"]:
        raise ValueError("OWNER_SOURCE_SIZE")
    digest=hashlib.sha256()
    with path.open("rb") as f:
        while block:=f.read(1024*1024): digest.update(block)
        if digest.hexdigest()!=entry["sha256"]: raise ValueError("OWNER_SOURCE_HASH")
        f.seek(0)
        magic,version,length=struct.unpack("<4sII",f.read(12))
        if (magic,version,length)!=(b"glTF",2,entry["bytes"]): raise ValueError("OWNER_GLB_HEADER")
        chunks=[]
        while f.tell()<length:
            raw=f.read(8)
            if len(raw)!=8: raise ValueError("OWNER_GLB_CHUNK")
            size,kind=struct.unpack("<I4s",raw)
            if size<=0 or size%4 or f.tell()+size>length:raise ValueError("OWNER_GLB_CHUNK")
            data=f.read(size) if kind==b"JSON" and size<=2*1024*1024 else None
            if data is None:f.seek(size,1)
            chunks.append((kind,size,data))
        if len(chunks)!=2 or chunks[0][0]!=b"JSON" or chunks[1][0]!=b"BIN\0" or chunks[0][2] is None:
            raise ValueError("OWNER_GLB_CHUNKS")
        doc=json.loads(chunks[0][2])
    if doc.get("asset",{}).get("version")!="2.0" or doc.get("extensionsRequired"):
        raise ValueError("OWNER_GLB_VERSION")
    meshes=doc.get("meshes",[])
    if len(meshes)!=1 or len(meshes[0].get("primitives",[]))!=1:raise ValueError("OWNER_GLB_MESH")
    prim=meshes[0]["primitives"][0]
    if prim.get("mode",4)!=4 or "indices" not in prim or "POSITION" not in prim.get("attributes",{}):
        raise ValueError("OWNER_GLB_PRIMITIVE")
    accessors=doc["accessors"]
    vertices=accessors[prim["attributes"]["POSITION"]]["count"]
    indices=accessors[prim["indices"]]["count"]
    if vertices!=entry["vertices"] or indices!=entry["triangles"]*3:
        raise ValueError("OWNER_GLB_GEOMETRY")
    if len(doc.get("animations",[]))!=entry["animation_clips"] or sum(len(s["joints"]) for s in doc.get("skins",[]))!=entry["skin_joints"]:
        raise ValueError("OWNER_GLB_METADATA")
    return {"alias":entry["alias"],"verified":True,"sha256":digest.hexdigest(),"triangles":entry["triangles"]}

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--assets",type=Path,required=True)
    p.add_argument("--manifest",type=Path,default=Path(__file__).resolve().parents[1]/"evidence/owner-public-glb-batch-20261020.json")
    p.add_argument("--only",nargs="*")
    args=p.parse_args()
    doc=json.loads(args.manifest.read_text(encoding="utf-8"))
    if doc.get("protocol")!="are.owner-public-glb-batch.v1" or len(doc.get("models",[]))!=10:
        raise ValueError("OWNER_MANIFEST_PROTOCOL")
    models=doc["models"]
    if len(set(x["alias"] for x in models))!=10 or sum(x["triangles"] for x in models)!=doc["total_triangles"] or sum(x["bytes"] for x in models)!=doc["total_bytes"]:
        raise ValueError("OWNER_MANIFEST_TOTALS")
    selected=args.only or [x["alias"] for x in models]
    if len(set(selected))!=len(selected) or any(x not in [y["alias"] for y in models] for x in selected):
        raise ValueError("OWNER_MANIFEST_SELECTION")
    result=[verify(args.assets/x["file"],x) for x in models if x["alias"] in selected]
    print(json.dumps({"protocol":"are.owner-public-glb-readback.v1","status":"PASS","source_files_modified":False,"models":result}))

if __name__=="__main__":main()
