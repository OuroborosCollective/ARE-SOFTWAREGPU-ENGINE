"""Pinned-vs-current MIHA Auto canonical evidence inventory (read-only).

The Hugging Face `auto` Viewer is a *projection* of canonical evidence,
not the actual SFT training rows. A live SHA change always requires a
new approved canonical->Atomic build, strict holdout leak-audit and readback.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

HEX40 = re.compile(r"[0-9a-f]{40}\Z")


def pinned_sha(value):
    if type(value) is not str or not HEX40.fullmatch(value):
        raise ValueError("AUTO_SHA: immutable 40-hex revision required")
    return value



def _trusted_snapshot_file(path, root):
    if not path.is_file():
        raise ValueError("AUTO_INVENTORY: canonical/viewer file not regular")
    if path.is_symlink():
        # snapshot_download uses regular symlinks into the content-addressed
        # blobs/ folder of the *same* repository cache. Do not follow arbitrary
        # paths, even if the linked file contains syntactically valid JSON.
        if root.parent.name != "snapshots" or not HEX40.fullmatch(root.name):
            raise ValueError("AUTO_INVENTORY: symlink outside HF snapshot")
        blobs = (root.parent.parent / "blobs").resolve()
        if not path.resolve().is_relative_to(blobs):
            raise ValueError("AUTO_INVENTORY: symlink escapes HF cache")


def pair_coverage(root):
    """List possible pairs by filename only; never certify their contents.

    This diagnostic is safe for incomplete live snapshots, but has no
    training eligibility meaning until the full canonical/Viewer verifier,
    source closure and Atomic/holdout audits have passed.
    """
    root = Path(root)
    canonical = {p.stem for p in (root / "data" / "auto").glob("*.json")}
    projections = {p.stem for p in (root / "data" / "auto_rows").glob("*.jsonl")}
    return {
        "canonical_count": len(canonical),
        "viewer_count": len(projections),
        "pair_count_unverified": len(canonical & projections),
        "missing_canonical_ids": sorted(projections - canonical),
        "missing_viewer_ids": sorted(canonical - projections),
        "training_eligible": False,
    }


def inventory(root):
    root = Path(root)
    canonical = root / "data" / "auto"
    projection = root / "data" / "auto_rows"
    docs = sorted(canonical.glob("*.json"))
    rows = sorted(projection.glob("*.jsonl"))
    canonical_ids, row_ids = {p.stem for p in docs}, {p.stem for p in rows}
    if not docs or len(docs) != len(rows) or canonical_ids != row_ids:
        raise ValueError("AUTO_INVENTORY: canonical/viewer paths differ or empty; "
                         + f"canonical={len(docs)},viewer={len(rows)},"
                         + f"missing_viewers={sorted(canonical_ids-row_ids)[:10]},"
                         + f"missing_canonical={sorted(row_ids-canonical_ids)[:10]}")
    for path in docs:
        _trusted_snapshot_file(path, root)
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            raise ValueError("AUTO_INVENTORY: invalid canonical JSON") from error
        if type(parsed) is not dict or parsed.get("record_id") != path.stem:
            raise ValueError("AUTO_INVENTORY: record-id mismatch")
    for path in rows:
        _trusted_snapshot_file(path, root)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) != 1 or not isinstance(json.loads(lines[0]), dict):
                raise ValueError("projection count")
        except (ValueError, OSError) as error:
            raise ValueError("AUTO_INVENTORY: invalid viewer row") from error
    return {"canonical_records": len(docs), "viewer_projection_rows": len(rows),
            "record_ids": [p.stem for p in docs]}


def compare(pinned_revision, current_revision, pinned, current):
    pinned_sha(pinned_revision)
    pinned_sha(current_revision)
    a, b = pinned.get("record_ids"), current.get("record_ids")
    if (not isinstance(a, list) or not a or len(a) != len(set(a)) or
            not isinstance(b, list) or not b or len(b) != len(set(b)) or
            pinned.get("canonical_records") != len(a) or
            current.get("canonical_records") != len(b)):
        raise ValueError("AUTO_INVENTORY: malformed inventory")
    aligned = pinned_revision == current_revision and a == b
    return {
        "protocol": "are.miha.auto-readiness.v1",
        "status": "PINNED_CURRENT" if aligned else "AUTO_REFRESH_REQUIRED",
        "pinned_evidence_sha": pinned_revision,
        "current_evidence_sha": current_revision,
        "pinned_canonical_records": len(a), "current_canonical_records": len(b),
        "added_ids": sorted(set(b) - set(a)), "removed_ids": sorted(set(a) - set(b)),
        "training_started": False, "release_accepted": False,
        "atomic_approved_for_live_auto": False,
        "notes": [
            "auto Viewer rows are one-record projections, not SFT examples",
            "PINNED_CURRENT means evidence SHA aligned only; Atomic/holdout audit still required",
            "source revision change requires reviewed rebuilt Atomic, holdout overlap and byte readback"
        ]
    }



def assess(pinned_revision, current_revision, pinned_root, current_root):
    """Identify invalid live Auto without approving or modifying its records.

    A damaged approved pinned snapshot is a hard failure. A damaged *newer*
    live snapshot is a signed BLOCKED finding, never a usable training input.
    """
    pinned_sha(pinned_revision)
    pinned_sha(current_revision)
    old = inventory(pinned_root)
    try:
        new = inventory(current_root)
    except ValueError as exc:
        if not str(exc).startswith("AUTO_INVENTORY:"):
            raise
        return {
            "protocol": "are.miha.auto-readiness.v1",
            "status": "AUTO_SOURCE_INVALID",
            "diagnostic": str(exc),
            "pair_coverage": pair_coverage(current_root),
            "pinned_evidence_sha": pinned_revision,
            "current_evidence_sha": current_revision,
            "pinned_canonical_records": old["canonical_records"],
            "current_canonical_records": None,
            "added_ids": [], "removed_ids": [],
            "training_started": False, "release_accepted": False,
            "atomic_approved_for_live_auto": False,
            "notes": ["live source invalid; repair canonical/viewer pair before Atomic rebuild",
                      "historical pinned Atomic training source remains unchanged"]
        }
    return compare(pinned_revision, current_revision, old, new)


def run(config_file, output):
    from huggingface_hub import HfApi, snapshot_download
    cfg = json.loads(Path(config_file).read_text(encoding="utf-8"))
    pinned = pinned_sha(cfg["evidence_revision"])
    # HfApi resolves the current live SHA, which is then used immutably to
    # download the files. No auto-following mutable main during training.
    current = pinned_sha(HfApi().dataset_info("Thorsu/miha-evidence").sha)
    kwargs = {"repo_id": "Thorsu/miha-evidence", "repo_type": "dataset",
              "allow_patterns": ["data/auto/*.json", "data/auto_rows/*.jsonl"]}
    old_path = snapshot_download(revision=pinned, **kwargs)
    new_path = snapshot_download(revision=current, **kwargs)
    receipt = assess(pinned, current, old_path, new_path)
    receipt["base_model_revision"] = pinned_sha(cfg["base_revision"])
    receipt["code_revision"] = pinned_sha(cfg["code_revision"])
    receipt["atomic_revision"] = pinned_sha(cfg["atomic_revision"])
    receipt["bench_revision"] = pinned_sha(cfg["bench_revision"])
    digest = hashlib.sha256(json.dumps(receipt, sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    receipt["sha256"] = digest
    dest = Path(output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("x", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, sort_keys=True)
        f.write("\n")
    if json.loads(dest.read_text(encoding="utf-8")) != receipt:
        raise ValueError("AUTO_READBACK")
    print(json.dumps({"status": receipt["status"], "sha256": digest,
                      "pinned": receipt["pinned_canonical_records"], "current": receipt["current_canonical_records"],
                      "training_started": False}), flush=True)
    return receipt


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="fixtures/miha/training.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.config, args.output)


if __name__ == "__main__":
    main()
