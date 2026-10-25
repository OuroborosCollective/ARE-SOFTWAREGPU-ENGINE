"""Fail-closed full-catalog plateau validation; no inference from rejection counts."""
import json
from pathlib import Path

def verify(catalog, attempts):
    if catalog.get("protocol") != "are.autoloop-cpu-catalog.v1":
        raise ValueError("CATALOG_PROTOCOL")
    candidates = catalog["candidates"]
    profiles = {(s, p, w) for s in catalog["scenes"] for p in catalog["pixels"] for w in catalog["workers"]}
    if not candidates or len(set(candidates)) != len(candidates) or not profiles:
        raise ValueError("CATALOG_INVALID")
    required = {(c,s,p,w) for c in candidates for s,p,w in profiles}
    sweeps = {}
    for a in attempts:
        if not isinstance(a, dict) or type(a.get("sweep")) is not int or a["sweep"] <= 0:
            raise ValueError("SWEEP_ID")
        key = (a.get("candidate"),a.get("scene"),a.get("pixels"),a.get("workers"))
        if key not in required:
            raise ValueError("UNKNOWN_CANDIDATE_PROFILE")
        if a.get("status") not in ("accepted","rejected","error"):
            raise ValueError("INVALID_VERDICT")
        if a["status"] in ("accepted","rejected") and (not a.get("receipt_sha256") or not a.get("ci_verified")):
            raise ValueError("UNVERIFIED_VERDICT")
        sweep=sweeps.setdefault(a["sweep"], {})
        if key in sweep:
            raise ValueError("DUPLICATE_VERDICT")
        sweep[key]=a["status"]
    streak=0
    complete=0
    for idx in range(1,max(sweeps,default=0)+1):
        sweep=sweeps.get(idx,{})
        if set(sweep)!=required or "error" in sweep.values():
            break
        complete=idx
        streak=0 if "accepted" in sweep.values() else streak+1
    return {"completed":streak>=3,"complete_sweeps":complete,"consecutive_no_gain_sweeps":streak,
            "candidate_count":len(candidates),"profile_count":len(profiles)}
