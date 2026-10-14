"""Prepare an immutable MIHA Auto candidate each time public Evidence grows.

No model weights, Hugging Face writes, paid Jobs, Trainer invocations or
automatic release acceptance. Real canonical builder and complete holdout
audit run at pinned builder/benchmark revisions before proposing SFT rows.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys

from software_gpu.training.auto_incremental import (
    inspect_release, make_replay_shards, plan_refresh, seal_plan
)
from software_gpu.training.auto_readiness import pinned_sha


def prepare(config, output, renderer_sha):
    from huggingface_hub import HfApi, snapshot_download

    cfg=json.loads(Path(config).read_text(encoding="utf-8"))
    pinned_sha(renderer_sha)
    for key in ("code_revision","base_revision","bench_revision",
                "evidence_revision","atomic_revision"):
        pinned_sha(cfg[key])
    dest=Path(output)
    dest.mkdir(parents=True,exist_ok=False)
    live_sha=pinned_sha(HfApi().dataset_info("Thorsu/miha-evidence").sha)
    code=snapshot_download(
        "Thorsu/miha-deepseek-r1-distill-qwen-7b-lora",
        revision=cfg["code_revision"],allow_patterns=["*.py"])
    # The builder is executed from the approved immutable code revision only;
    # never import a file from the mutable Evidence repository.
    sys.path.insert(0,str(code))
    builder=importlib.import_module("dataset_pipeline")

    bench=snapshot_download("Thorsu/miha-bench",repo_type="dataset",
                            revision=cfg["bench_revision"],
                            allow_patterns=["data/test.jsonl"])
    kwargs={"repo_id":"Thorsu/miha-evidence","repo_type":"dataset",
            "allow_patterns":["data/auto/*.json","data/auto_rows/*.jsonl"]}
    old=snapshot_download(revision=cfg["evidence_revision"],**kwargs)
    new=snapshot_download(revision=live_sha,**kwargs)
    published=snapshot_download("Thorsu/miha-train-atomic",
                                repo_type="dataset",revision=cfg["atomic_revision"],
                                allow_patterns=["data/train.jsonl*","build_manifest.json"])
    old_manifest=builder.build(old,bench,{"miha-evidence":cfg["evidence_revision"],
                                         "miha-bench":cfg["bench_revision"]},
                               dest/"approved-rebuilt")
    old_hub=inspect_release(published)
    if old_manifest!=old_hub["manifest"]:
        raise ValueError("AUTO_APPROVED_DUAL_READBACK_MISMATCH")

    try:
        builder.build(new,bench,{"miha-evidence":live_sha,
                                 "miha-bench":cfg["bench_revision"]},
                      dest/"candidate")
    except (ValueError,FileNotFoundError,KeyError) as exc:
        blocked={
            "protocol":"are.miha.growing-atomic.plan.v1",
            "status":"SOURCE_BLOCKED",
            "blocker_type":type(exc).__name__,
            "diagnostic":str(exc)[:1000],
            "previous_evidence_sha":cfg["evidence_revision"],
            "candidate_evidence_sha":live_sha,
            "training_started":False,"release_accepted":False,
            "approved_atomic_revision":None,
            "candidate_atomic_ready":False
        }
        seal_plan(blocked,dest/"plan.json")
        print(json.dumps({"status":"SOURCE_BLOCKED","sha":live_sha,
                          "training_started":False}),flush=True)
        return blocked

    previous=inspect_release(dest/"approved-rebuilt")
    candidate=inspect_release(dest/"candidate")
    plan=plan_refresh(previous,candidate,renderer_sha)
    plan["approved_atomic_revision_before_refresh"]=cfg["atomic_revision"]
    plan["candidate_atomic_ready"]=True
    plan["candidate_shards"]=make_replay_shards(candidate,max_rows=2048,seed=42)
    seal_plan(plan,dest/"plan.json")
    print(json.dumps({
        "status":plan["status"],
        "evidence_sha":live_sha,
        "examples":len(plan["all_training_example_ids"]),
        "new_examples":len(plan["new_example_ids"]),
        "training_started":False,"release_accepted":False}),flush=True)
    return plan


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",default="fixtures/miha/training.json")
    parser.add_argument("--output",required=True)
    parser.add_argument("--renderer-sha",required=True)
    args=parser.parse_args()
    prepare(args.config,args.output,args.renderer_sha)


if __name__=="__main__":
    main()
