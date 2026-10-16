"""Immutable, review-gated growing MIHA Atomic training snapshots.

This is planning, not a trainer. Builds must come from the pinned real
canonical->Atomic builder; a Viewer row never becomes SFT input directly.
"""
from __future__ import annotations
import gzip
import hashlib
import json
from pathlib import Path
import random
import re

H40=re.compile(r"[0-9a-f]{40}\Z")
H64=re.compile(r"[0-9a-f]{64}\Z")


def canonical(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()


def inspect_release(directory):
    root=Path(directory)
    manifest=json.loads((root/"build_manifest.json").read_text(encoding="utf-8"))
    data_dir = root/"data" if (root/"data").is_dir() else root
    plain, zipped = data_dir/"train.jsonl", data_dir/"train.jsonl.gz"
    if not plain.is_file() and not zipped.is_file():
        raise ValueError("AUTO_RELEASE_HASH missing Atomic SFT")
    data=plain.read_bytes() if plain.is_file() else gzip.decompress(zipped.read_bytes())
    if zipped.is_file() and gzip.decompress(zipped.read_bytes())!=data:
        raise ValueError("AUTO_RELEASE_HASH transport conflict")
    if manifest.get("train_jsonl_sha256")!=hashlib.sha256(data).hexdigest():
        raise ValueError("AUTO_RELEASE_HASH")
    records=manifest.get("records")
    if (type(records) is not dict or not records or
        any(type(k) is not str or type(v) is not str or not H64.fullmatch(v)
            for k,v in records.items())):
        raise ValueError("AUTO_RELEASE_PIN invalid canonical records")
    for key in ("dataset_revision","benchmark_revision"):
        if type(manifest.get(key)) is not str or not H40.fullmatch(manifest[key]):
            raise ValueError("AUTO_RELEASE_PIN invalid revision")
    if manifest.get("overlap",{}).get("overlap")!=0:
        raise ValueError("AUTO_RELEASE_HOLDOUT")
    if (manifest.get("source_dataset")!="Thorsu/miha-evidence" or
        manifest.get("output_contract")!="miha-five-key-v1" or
        manifest.get("contains_hidden_chain_of_thought") is not False):
        raise ValueError("AUTO_RELEASE_CONTRACT")
    rows=[json.loads(line) for line in data.splitlines()]
    ids=[r.get("id") for r in rows]
    if (len(ids)!=len(set(ids)) or len(rows)!=manifest.get("examples") or
        ids != manifest.get("training_example_ids")):
        raise ValueError("AUTO_RELEASE_DUPLICATES")
    if any(r.get("origin_record_id") not in records for r in rows):
        raise ValueError("AUTO_RELEASE_ORIGIN")
    digests={r["id"]:hashlib.sha256(canonical(r)).hexdigest() for r in rows}
    return {"manifest":manifest, "row_hashes":digests,
            "origin_by_id":{r["id"]:r["origin_record_id"] for r in rows},
            "example_ids":ids,"records":records,"sha256":hashlib.sha256(data).hexdigest()}


def plan_refresh(previous, latest, renderer_sha):
    if type(renderer_sha) is not str or not H40.fullmatch(renderer_sha):
        raise ValueError("AUTO_RELEASE_PIN")
    a,b=previous["manifest"],latest["manifest"]
    if a["benchmark_revision"]!=b["benchmark_revision"] or a.get("builder_code_sha256")!=b.get("builder_code_sha256"):
        raise ValueError("AUTO_RELEASE_PIN builder or holdout revision changed")
    previous_ids, latest_ids=set(previous["row_hashes"]),set(latest["row_hashes"])
    added=sorted(latest_ids-previous_ids)
    removed=sorted(previous_ids-latest_ids)
    changed=sorted(k for k in previous_ids & latest_ids if previous["row_hashes"][k]!=latest["row_hashes"][k])
    records_changed=sorted(k for k in previous["records"].keys()&latest["records"].keys()
                           if previous["records"][k]!=latest["records"][k])
    any_change = a["dataset_revision"]!=b["dataset_revision"] or previous["sha256"]!=latest["sha256"]
    if removed or changed or records_changed or set(previous["records"])-set(latest["records"]):
        status="CORRECTION_REVIEW_REQUIRED"
    elif any_change:
        status="CANDIDATE_READY_FOR_REVIEW"
    else: status="NO_CHANGE"
    return {
      "protocol":"are.miha.growing-atomic.plan.v1",
      "status":status, "strategy":"full-corpus-replay",
      "previous_evidence_sha":a["dataset_revision"],
      "candidate_evidence_sha":b["dataset_revision"],
      "benchmark_sha":b["benchmark_revision"],
      "renderer_sha":renderer_sha,
      "source_manifest_sha256":hashlib.sha256(canonical(b)).hexdigest(),
      "dataset_sha256":latest["sha256"],
      "new_example_ids":added,"removed_example_ids":removed,
      "changed_example_ids":changed,"changed_record_ids":records_changed,
      "all_training_example_ids":latest["example_ids"],
      "training_started":False,"release_accepted":False,
      "approved_atomic_revision":None,
      "required_gates":["canonical_to_atomic_rebuild","zero_holdout_overlap",
                        "immutable_atomic_Hub_readback","cpu_memory_16GiB",
                        "longest_example_backward","full_holdout_quality"],
    }



def select_training_snapshot(settings, inspected_release, *, approved_atomic_sha,
                             current_evidence_sha):
    """Switch to an approved immutable Atomic release without changing code pins.

    This is a proposed *input config*, not training or release acceptance.
    The caller must verify approved_atomic_sha by a real Hub SHA-bound readback
    and run scripts/miha_cpu_runner.py audit on the returned configuration.
    """
    def check_sha(s):
        return type(s) is str and bool(H40.fullmatch(s))
    if not check_sha(approved_atomic_sha) or not check_sha(current_evidence_sha):
        raise ValueError("AUTO_DYNAMIC: unpinned dataset revision")
    required=("code_revision","evidence_revision","atomic_revision",
              "base_revision","bench_revision")
    if (type(settings) is not dict or any(not check_sha(settings.get(n))
                                          for n in required)
        or settings.get("base_model")!="Qwen/Qwen2.5-0.5B-Instruct"):
        raise ValueError("AUTO_DYNAMIC: invalid existing training pins")
    manifest=inspected_release.get("manifest",{})
    if (manifest.get("dataset_revision")!=current_evidence_sha
        or manifest.get("benchmark_revision")!=settings["bench_revision"]
        or manifest.get("source_dataset")!="Thorsu/miha-evidence"
        or manifest.get("output_contract")!="miha-five-key-v1"
        or manifest.get("overlap",{}).get("overlap")!=0
        or inspected_release.get("sha256")!=manifest.get("train_jsonl_sha256")
        or not inspected_release.get("example_ids")):
        raise ValueError("AUTO_DYNAMIC: stale, unverified or mismatched SFT")
    selected={k:settings[k] for k in ("code_revision","base_model","base_revision",
                                      "evidence_revision","atomic_revision","bench_revision")}
    selected["evidence_revision"]=current_evidence_sha
    selected["atomic_revision"]=approved_atomic_sha
    return selected



def approve_training_snapshot(settings, inspected_release, *, atomic_sha,
                              live_evidence_sha):
    """Only the configured approved Atomic SHA can become a training input.

    Current public Evidence HEAD is observational metadata, not a requirement
    that invalidates a previously approved immutable dataset. Every selection
    is still AUDIT_REQUIRED: the caller must rebuild the pinned canonical
    source and check identical published Atomic bytes before any training.
    """
    if (type(settings) is not dict or type(atomic_sha) is not str
            or not H40.fullmatch(atomic_sha)
            or atomic_sha != settings.get("atomic_revision")):
        raise ValueError("AUTO_DYNAMIC_APPROVAL_MISSING: Atomic is not the configured approved release")
    if type(live_evidence_sha) is not str or not H40.fullmatch(live_evidence_sha):
        raise ValueError("AUTO_DYNAMIC: live Evidence SHA must be pinned")
    manifest = inspected_release.get("manifest", {})
    source_sha = manifest.get("dataset_revision")
    selected = select_training_snapshot(
        settings, inspected_release,
        approved_atomic_sha=atomic_sha,
        current_evidence_sha=source_sha,
    )
    return {
        "protocol": "are.miha.approved-snapshot-selection.v1",
        "status": "AUDIT_REQUIRED",
        "freshness": ("APPROVED_PINNED_CURRENT"
                      if source_sha == live_evidence_sha
                      else "APPROVED_PINNED_BEHIND_LIVE"),
        "training_config": selected,
        "approved_atomic_sha": atomic_sha,
        "training_evidence_sha": source_sha,
        "live_evidence_sha": live_evidence_sha,
        "dataset_sha256": inspected_release["sha256"],
        "examples": len(inspected_release["example_ids"]),
        "training_started": False,
        "release_accepted": False,
        "next_required_gate": "canonical-to-Atomic builder audit and byte readback",
    }



def make_replay_shards(release,max_rows=2048,seed=42):
    if type(max_rows) is not int or max_rows<1 or type(seed) is not int:
        raise ValueError("AUTO_REPLAY_SHARD")
    groups={}
    for id_ in release["example_ids"]:
        groups.setdefault(release["origin_by_id"][id_],[]).append(id_)
    if any(len(x)>max_rows for x in groups.values()):
        raise ValueError("AUTO_REPLAY_SHARD origin would split")
    names=sorted(groups)
    random.Random(seed).shuffle(names)
    result=[]; current=[]
    for name in names:
        group=groups[name]
        if current and len(current)+len(group)>max_rows:
            result.append({"index":len(result),"ids":current,"count":len(current)})
            current=[]
        current.extend(group)
    if current:result.append({"index":len(result),"ids":current,"count":len(current)})
    assert sorted(id_ for part in result for id_ in part["ids"])==sorted(release["example_ids"])
    return result


def seal_plan(plan,path):
    path=Path(path)
    report={**plan,"sha256":hashlib.sha256(canonical(plan)).hexdigest()}
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2,sort_keys=True)
        f.write("\n")
    if json.loads(path.read_text(encoding="utf-8"))!=report:
        raise ValueError("AUTO_RELEASE_READBACK")
    return report
