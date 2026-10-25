"""Fail-closed, read-only public CPU ranking builder. No renderer is started."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import urllib.request

REPOSITORY = "OuroborosCollective/ARE-SOFTWAREGPU-ENGINE"
RECEIPT_PROTOCOL = "are.autoloop-cpu-acceptance.v1"
BOARD_PROTOCOL = "are.autoloop-public-leaderboard.v1"
SCENES = ("tiny", "small-triangles", "large-surfaces", "procedural400", "procedural5k")
RESOLUTIONS = (64, 128)
WORKERS = (1, 2)
REQUIRED_SOURCES = (
    "software_gpu/benchmarks/compare_surface_plans.py",
    "software_gpu/benchmarks/compare_tile_backends.py",
    "software_gpu/integrations/aurion/offline_render_worker.py",
    "software_gpu/graphics/rasterizer.py",
    "software_gpu/graphics/geometry.py",
    "software_gpu/graphics/tile_backend.py",
    "software_gpu/graphics/surface_plan.py",
    "software_gpu/graphics/framebuffer.py",
    "software_gpu/graphics/batch_shader.py",
    "software_gpu/graphics/shader.py",
)
CI_URL = re.compile(r"https://github\.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/([1-9][0-9]*)\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")

def require(condition, error):
    if not condition:
        raise ValueError(error)

def digest(data):
    body = {k: v for k, v in data.items() if k != "sha256"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()

def good_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0

def validate_receipt(receipt, root, ci):
    require(isinstance(receipt, dict) and receipt.get("protocol") == RECEIPT_PROTOCOL, "RECEIPT_PROTOCOL")
    require(receipt.get("sha256") == digest(receipt), "RECEIPT_SHA")
    require(type(receipt.get("sequence")) is int and receipt["sequence"] > 0, "SEQUENCE_INVALID")
    source, baseline = receipt.get("source_commit"), receipt.get("baseline_commit")
    require(bool(HEX40.fullmatch(str(source))) and bool(HEX40.fullmatch(str(baseline))) and source != baseline, "REVISION_INVALID")
    require(receipt.get("render_scope") == "whole-draw CPU RGBA8 plus float32 depth", "RENDER_SCOPE")
    env = receipt.get("environment")
    require(isinstance(env, dict) and all(isinstance(env.get(k), str) and env[k].strip() for k in ("runner", "cpu", "python", "numpy")) and env.get("workers") == [1, 2], "ENVIRONMENT_INVALID")
    hashes = receipt.get("source_sha256")
    require(isinstance(hashes, dict) and set(hashes) == set(REQUIRED_SOURCES), "SOURCE_SET")
    root = Path(root).resolve()
    for name in REQUIRED_SOURCES:
        path = (root / name).resolve()
        require(path.is_file() and root in path.parents, "SOURCE_MISSING")
        require(bool(HEX64.fullmatch(str(hashes[name]))), "SOURCE_HASH_FORMAT")
        require(hashlib.sha256(path.read_bytes()).hexdigest() == hashes[name], "SOURCE_DRIFT:" + name)
    match = CI_URL.fullmatch(str(receipt.get("ci_url")))
    require(match is not None, "CI_URL_INVALID")
    require(isinstance(ci, dict) and ci.get("id") == int(match.group(1)), "CI_RUN_ID")
    require(ci.get("repository", {}).get("full_name") == REPOSITORY, "CI_REPOSITORY")
    require(ci.get("head_sha") == source, "CI_HEAD")
    require(ci.get("status") == "completed" and ci.get("conclusion") == "success", "CI_NOT_GREEN")
    require(ci.get("event") in ("pull_request", "workflow_dispatch", "push"), "CI_EVENT")
    target = {(s, p, w) for s in SCENES for p in RESOLUTIONS for w in WORKERS}
    rows = receipt.get("profiles")
    require(isinstance(rows, list) and len(rows) == len(target), "PROFILE_COVERAGE")
    seen, entries, round_ratios = set(), [], [[], []]
    for row in rows:
        require(isinstance(row, dict), "PROFILE_INVALID")
        key = row.get("scene"), row.get("pixels"), row.get("workers")
        require(key in target and key not in seen, "PROFILE_COVERAGE")
        seen.add(key)
        for domain in ("rgba", "depth"):
            before = row.get("baseline_" + domain + "_sha256")
            after = row.get("candidate_" + domain + "_sha256")
            require(bool(HEX64.fullmatch(str(before))) and before == after, "FRAME_PARITY_" + domain.upper())
        rounds = row.get("rounds")
        require(isinstance(rounds, list) and len(rounds) == 2, "SAMPLES_ROUNDS_REQUIRED")
        measurements = []
        for i, round_doc in enumerate(rounds):
            pairs = round_doc.get("pairs") if isinstance(round_doc, dict) else None
            require(isinstance(pairs, list) and len(pairs) == 15, "SAMPLES_15_REQUIRED")
            before, after = [], []
            for j, pair in enumerate(pairs):
                require(isinstance(pair, dict), "PAIR_INVALID")
                first = "baseline" if (i + j) % 2 == 0 else "candidate"
                second = "candidate" if first == "baseline" else "baseline"
                require(pair.get("order") == [first, second], "ORDER_NOT_ALTERNATING")
                a, b = pair.get("baseline_ms"), pair.get("candidate_ms")
                require(good_number(a) and good_number(b), "TIMING_INVALID")
                before.append(a)
                after.append(b)
            ratio = statistics.median(a / b for a, b in zip(before, after))
            require(ratio >= 0.98, "PROFILE_REGRESSION")
            round_ratios[i].append(ratio)
            measurements.append((statistics.median(before), statistics.median(after), ratio))
        entries.append({
            "profile": "%s · %d worker%s" % (key[0], key[2], "" if key[2] == 1 else "s"),
            "pixels": key[1], "workers": key[2], "samples": 30,
            "baseline_ms": statistics.median(m[0] for m in measurements),
            "candidate_ms": statistics.median(m[1] for m in measurements),
            "speedup": statistics.median(m[2] for m in measurements),
            "image_parity": True, "ci_verified": True, "source_commit": source,
            "ci_url": receipt["ci_url"], "source_receipt_sha256": receipt["sha256"]
        })
    require(seen == target, "PROFILE_COVERAGE")
    for ratios in round_ratios:
        require(math.exp(sum(math.log(x) for x in ratios) / len(ratios)) >= 1.02, "GAIN_BELOW_THRESHOLD")
    return sorted(entries, key=lambda e: (e["pixels"], e["workers"], e["profile"]))

def build_board(receipts, root, read_ci):
    require(len(receipts) <= 100, "RECEIPT_CATALOG_OVER_BUDGET")
    versions, sources, latest = set(), [], {}
    for receipt in sorted(receipts, key=lambda x: x.get("sequence", 0)):
        number = receipt.get("sequence")
        require(number not in versions, "SEQUENCE_DUPLICATE")
        versions.add(number)
        entries = validate_receipt(receipt, root, read_ci(receipt["ci_url"]))
        sources.append({k: receipt[k] for k in ("sequence", "source_commit", "baseline_commit", "ci_url")})
        sources[-1]["receipt_sha256"] = receipt["sha256"]
        sources[-1]["environment"] = receipt["environment"]
        for entry in entries:
            latest[entry["profile"], entry["pixels"], entry["workers"]] = entry
    return {
        "protocol": BOARD_PROTOCOL,
        "scope": "latest independently CI-verified same-host whole-draw CPU measurements per profile; no GPU or FPS comparison",
        "sources": sources,
        "entries": [latest[k] for k in sorted(latest, key=lambda x: (x[1], x[2], x[0]))]
    }

def plateau_state(attempts, candidates, profiles):
    """Stop after three complete error-free catalog sweeps without an acceptance."""
    require(bool(candidates) and bool(profiles) and len(set(candidates)) == len(candidates) and len(set(profiles)) == len(profiles), "PLATEAU_CATALOG")
    expected = {(c, p) for c in candidates for p in profiles}
    groups = {}
    for attempt in attempts:
        n, key = attempt.get("sweep"), (attempt.get("candidate"), attempt.get("profile"))
        require(type(n) is int and n > 0 and key in expected and attempt.get("status") in ("accepted", "rejected", "error"), "PLATEAU_ATTEMPT_INVALID")
        rows = groups.setdefault(n, {})
        require(key not in rows, "PLATEAU_DUPLICATE_ATTEMPT")
        rows[key] = attempt["status"]
    no_gain, complete = 0, 0
    for n in range(1, max(groups, default=0) + 1):
        rows = groups.get(n)
        if rows is None or set(rows) != expected or "error" in rows.values():
            break
        complete = n
        no_gain = 0 if "accepted" in rows.values() else no_gain + 1
    return {"completed": no_gain >= 3, "consecutive_no_gain_sweeps": no_gain,
            "last_complete_sweep": complete, "required_complete_sweeps": 3}

def read_ci(url):
    match = CI_URL.fullmatch(str(url))
    require(match is not None, "CI_URL_INVALID")
    req = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY + "/actions/runs/" + match.group(1),
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ARE-SoftwareGPU-Publisher",
                 **({"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"]} if os.getenv("GITHUB_TOKEN") else {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)
    except (OSError, ValueError) as exc:
        raise ValueError("CI_LOOKUP_FAILED") from exc

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument("--receipts", default="evidence/autoloop/accepted")
    p.add_argument("--output", default="evidence/autoloop-accepted-leaderboard-v1.json")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = p.parse_args(argv)
    root = args.root.resolve()
    folder = (root / args.receipts).resolve()
    destination = (root / args.output).resolve()
    require(root in folder.parents and root in destination.parents, "PATH_OUTSIDE_ROOT")
    paths = sorted(folder.glob("*.json")) if folder.is_dir() else []
    require(len(paths) <= 100, "RECEIPT_CATALOG_OVER_BUDGET")
    receipts = []
    for path in paths:
        require(path.is_file() and path.stat().st_size <= 512 * 1024, "RECEIPT_SIZE_BUDGET")
        receipts.append(json.loads(path.read_text(encoding="utf-8")))
    result = build_board(receipts, root, read_ci)
    output = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.check:
        require(destination.is_file() and destination.read_text(encoding="utf-8") == output, "PUBLIC_LEADERBOARD_DRIFT")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_suffix(".tmp")
        tmp.write_text(output, encoding="utf-8")
        tmp.replace(destination)
        require(destination.read_text(encoding="utf-8") == output, "PUBLIC_LEADERBOARD_READBACK")
    print(json.dumps({"status": "VERIFIED", "sources": len(receipts), "entries": len(result["entries"])}))

if __name__ == "__main__":
    main()
