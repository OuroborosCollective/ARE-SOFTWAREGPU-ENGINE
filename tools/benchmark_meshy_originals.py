#!/usr/bin/env python3
"""Original Meshy assets: real native C++17 pose + framebuffer, bounded and SHA-bound."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from software_gpu.research.model_probe import build_model_probe, load_asset, write_scene, run_model
from tools.meshy_originals import load_manifest, verify

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--assets",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--seconds",type=int,default=480)
    args=p.parse_args()
    if args.seconds < 30 or args.seconds > 600:
        p.error("bounded 30..600 seconds")
    out=args.output_dir
    out.mkdir(parents=True,exist_ok=True)
    start=time.monotonic()
    assets=load_manifest()["assets"][:2]
    exe,build=build_model_probe(out/"native-build")
    receipts=[]
    for asset_ref in assets:
        if time.monotonic()-start>args.seconds:
            raise RuntimeError("MESHY_TOTAL_TIME_BUDGET")
        source=args.assets/asset_ref["file"]
        source_receipt=verify(source,asset_ref)
        # Offline read+typed preparation; C++17 executes skin, pose, project and raster.
        asset=load_asset(source,asset_ref,profile="diagnostic")
        if len(asset["faces"])!=asset_ref["triangles"] or len(asset["positions"])!=asset_ref["vertices"]:
            raise ValueError("MESHY_GEOMETRY_COUNT_DRIFT")
        clip=0 if asset["clips"] else None
        req=out/(asset_ref["alias"]+".aremdl")
        scene=dict(asset=asset,clip=clip,color=[180,190,210,255])
        input_receipt=write_scene(req,[scene],[0.0],pixels=128,tile=32)
        remain=max(1,int(args.seconds-(time.monotonic()-start)))
        if remain<30:
            raise RuntimeError("MESHY_TOTAL_TIME_BUDGET")
        result=run_model(exe,req,workers=2,repeats=1,mode="render",
                         timeout=min(remain,300),render_profile="diagnostic")
        digest=hashlib.sha256()
        for key in ("rgba","depth"):
            # Fail closed on absent output fields; no synthetic frame substitutions.
            value=result[key]
            digest.update(value.tobytes() if isinstance(value,np.ndarray) else value)
        receipts.append(dict(alias=asset_ref["alias"],source=source_receipt,
                             input_sha256=input_receipt["sha256"],frames=1,
                             mode="native-c++17-diagnostic",
                             render_buffer_sha256=digest.hexdigest(),
                             runtime_receipt=result["receipt"]))
        print("REAL_NATIVE_MESHY_OK",asset_ref["alias"],digest.hexdigest(),flush=True)
    doc=dict(protocol="are.meshy.real-native-frames.v1",status="PASS",
             originals_modified=False,model_build=build,
             caveats=["Diagnostic flat-color, not source-textured PBR","One frame per original","Not a game FPS claim",
                      "No native maize render yet; no rig animation for dragon"],
             models=receipts)
    (out/"native-evidence.json").write_text(json.dumps(doc,sort_keys=True,indent=2,default=str)+"\n")
    print("MESHY_NATIVE_RECEIPTS_OK")

if __name__=="__main__":
    main()
