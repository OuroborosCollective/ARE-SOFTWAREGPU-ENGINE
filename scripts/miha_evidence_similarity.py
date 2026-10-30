"""Offline source-ID Dice candidate discovery; not a proof or causal join."""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path
import re

SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")

def load(path):
    raw = path.read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError("MIHA_INPUT_TOO_LARGE")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()

def analyze(data, digest):
    if not isinstance(data, dict) or data.get("schema") != "miha.source-multisets.v1":
        raise ValueError("MIHA_SCHEMA")
    revision = data.get("dataset_revision")
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise ValueError("MIHA_UNPINNED_REVISION")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("MIHA_INPUT_SHA256")
    rows = data.get("records")
    if not isinstance(rows, list) or not 2 <= len(rows) <= 128:
        raise ValueError("MIHA_RECORD_BOUNDS")
    counters = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not IDENT.fullmatch(row["id"]):
            raise ValueError("MIHA_RECORD_ID")
        ids = row.get("source_ids")
        if not isinstance(ids, list) or len(ids) > 256 or any(
            not isinstance(x, str) or not x or len(x) > 512 or any(c.isspace() or ord(c) < 32 for c in x)
            for x in ids
        ):
            raise ValueError("MIHA_SOURCE_IDS")
        if row["id"] in counters:
            raise ValueError("MIHA_DUPLICATE_RECORD")
        counters[row["id"]] = Counter(ids)
    pairs, insufficient = [], 0
    for left, right in itertools.combinations(sorted(counters), 2):
        a, b = counters[left], counters[right]
        if not a or not b:
            insufficient += 1
            continue
        shared = {key: min(a[key], b[key]) for key in sorted(a.keys() & b.keys())}
        total = sum(a.values()) + sum(b.values())
        pairs.append({"left_id": left, "right_id": right,
                      "dice_dissimilarity": str(Fraction(total - 2 * sum(shared.values()), total)),
                      "shared_counts": shared})
    pairs.sort(key=lambda x: (Fraction(x["dice_dissimilarity"]), x["left_id"], x["right_id"]))
    return {"schema": "miha.source-similarity-candidates.v1",
            "status": "CANDIDATE_ONLY_NOT_PROOF", "dataset_revision": revision,
            "declared_revision_verified": False, "input_sha256": digest,
            "insufficient_evidence_pairs": insufficient, "pairs": pairs}

def save_result(path, data):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True, indent=2)
    if json.loads(path.read_text()) != data:
        raise RuntimeError("MIHA_RECEIPT_READBACK")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data, digest = load(args.input)
    result = analyze(data, digest)
    save_result(args.output, result)
    print(json.dumps({"status": result["status"], "pairs": len(result["pairs"])}))
