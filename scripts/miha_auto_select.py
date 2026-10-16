"""Resolve newest fully pinned MIHA Atomic release to a CPU training config.

This performs Hub readback only. Real canonical->Atomic audit is mandatory
afterwards; this script never invokes Trainer, GPU or a provider write.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

from software_gpu.training.auto_incremental import (
    canonical, inspect_release, approve_training_snapshot
)
from software_gpu.training.auto_readiness import pinned_sha


def resolve(config, output, atomic_sha=None):
    from huggingface_hub import HfApi, snapshot_download
    existing=json.loads(Path(config).read_text(encoding="utf-8"))
    api=HfApi()
    actual_evidence_sha=pinned_sha(api.dataset_info("Thorsu/miha-evidence").sha)
    if atomic_sha is None:
        atomic_sha=existing["atomic_revision"]
    atomic_sha=pinned_sha(atomic_sha)
    approved=snapshot_download("Thorsu/miha-train-atomic",repo_type="dataset",
                               revision=atomic_sha,
                               allow_patterns=["build_manifest.json",
                                               "data/train.jsonl*"])
    release=inspect_release(approved)
    # Keep the pinned original builder as the only trainer-input authority.
    model_code=snapshot_download(
        "Thorsu/miha-deepseek-r1-distill-qwen-7b-lora",
        revision=pinned_sha(existing["code_revision"]),
        allow_patterns=["dataset_pipeline.py"])
    pinned_builder_hash=hashlib.sha256(
        (Path(model_code)/"dataset_pipeline.py").read_bytes()).hexdigest()
    if release["manifest"].get("builder_code_sha256")!=pinned_builder_hash:
        raise ValueError("AUTO_DYNAMIC: published Atomic was built using different builder")
    approved=approve_training_snapshot(
        existing,release,atomic_sha=atomic_sha,
        live_evidence_sha=actual_evidence_sha
    )
    selected=approved["training_config"]
    target=Path(output)
    target.mkdir(parents=True,exist_ok=False)
    config_path=target/"training.json"
    with config_path.open("x",encoding="utf-8") as handle:
        json.dump(selected,handle,indent=2,sort_keys=True)
        handle.write("\n")
    receipt={
        "protocol":"are.miha.dynamic-training-config.v1",
        "freshness":approved["freshness"],
        "status":"AUDIT_REQUIRED",
        "atomic_revision":atomic_sha,
        "evidence_revision":selected["evidence_revision"],
        "observed_live_evidence_revision":actual_evidence_sha,
        "benchmark_revision":selected["bench_revision"],
        "code_revision":selected["code_revision"],
        "builder_sha256":pinned_builder_hash,
        "dataset_sha256":release["sha256"],
        "examples":len(release["example_ids"]),
        "training_started":False,"release_accepted":False,
        "next_required_gate":"scripts/miha_cpu_runner.py audit --config training.json"
    }
    receipt_hash=hashlib.sha256(canonical(receipt)).hexdigest()
    receipt["sha256"]=receipt_hash
    receipt_path=target/"resolution.json"
    with receipt_path.open("x",encoding="utf-8") as handle:
        json.dump(receipt,handle,indent=2,sort_keys=True)
        handle.write("\n")
    if (json.loads(config_path.read_text(encoding="utf-8"))!=selected or
        json.loads(receipt_path.read_text(encoding="utf-8"))!=receipt):
        raise ValueError("AUTO_DYNAMIC: readback differs")
    print(json.dumps({"status":"AUDIT_REQUIRED","examples":receipt["examples"],
                      "atomic_sha":atomic_sha,"receipt_sha256":receipt_hash,
                      "training_started":False}),flush=True)
    return receipt


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",default="fixtures/miha/training.json")
    parser.add_argument("--atomic-revision",
                        help="Exact reviewed Atomic revision; if omitted, inspect current Hub head")
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    resolve(args.config,args.output,args.atomic_revision)


if __name__=="__main__":
    main()
