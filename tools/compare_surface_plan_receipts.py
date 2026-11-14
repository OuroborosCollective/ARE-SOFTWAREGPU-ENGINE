"""Fail-closed comparison of two REAL CPU surface-plan benchmark receipts.

This tool NEVER runs a renderer and NEVER certifies a causal speedup. The input
receipts must come from two actual 15+ repetition full-draw executions of
software_gpu.benchmarks.compare_surface_plans, with matching host, scene and
reference image/depth bytes. Synthetic data is acceptable ONLY for parser tests,
never as performance evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

PROTOCOL = "are.cpu-e2e-revision-compare.v1"
INPUT_PROTOCOL = "are.surface-plan-benchmark.v1"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
MIN_REPEATS = 15
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
REQUIRED_SOURCES = frozenset((
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
))


class EvidenceRejected(ValueError):
    """Invalid or non-comparable measurements; never interpreted as a pass."""


def require(ok: bool, code: str) -> None:
    if not ok:
        raise EvidenceRejected(code)


def _sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _finite_positive(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * percentile
    low, high = math.floor(k), math.ceil(k)
    return ordered[low] + (ordered[high] - ordered[low]) * (k - low)


def audit(receipt: dict) -> dict[str, dict]:
    """Validate schema and reported aggregates; do not claim to rerender data."""
    require(isinstance(receipt, dict) and receipt.get("protocol") == INPUT_PROTOCOL,
            "RECEIPT_PROTOCOL_INVALID")
    checkout = receipt.get("checkout")
    require(isinstance(checkout, dict)
            and isinstance(checkout.get("head"), str)
            and _GIT_SHA.fullmatch(checkout["head"]) is not None
            and checkout.get("tracked_sources_clean") is True, "GIT_REVISION_UNVERIFIED")
    require(_sha256(receipt.get("benchmark_source_sha256"))
            and _sha256(receipt.get("fixture_source_sha256")),
            "BENCHMARK_SOURCE_UNBOUND")
    sources = receipt.get("source_paths_sha256")
    require(isinstance(sources, dict) and REQUIRED_SOURCES <= sources.keys()
            and all(_sha256(digest) for digest in sources.values()),
            "SOURCE_HASHES_INVALID")
    require(all(isinstance(receipt.get(key), str) and receipt[key]
                for key in ("python", "numpy", "os")), "ENVIRONMENT_UNBOUND")
    require(isinstance(receipt.get("environment"), dict)
            and isinstance(receipt["environment"].get("cpu_model"), str)
            and bool(receipt["environment"]["cpu_model"])
            and isinstance(receipt["environment"].get("thread_env"), dict),
            "HOST_IDENTITY_UNBOUND")
    cases = receipt.get("results")
    require(isinstance(cases, list) and bool(cases), "SCENES_MISSING")
    seen: dict[str, dict] = {}
    for case in cases:
        require(isinstance(case, dict) and isinstance(case.get("scene"), str)
                and bool(case["scene"]) and case["scene"] not in seen, "SCENE_DUPLICATE_OR_INVALID")
        require(case.get("byte_identical") is True
                and case.get("gpu_parity_established") is False
                and _sha256(case.get("image_sha256")),
                "FRAME_PARITY_UNVERIFIED")
        require(isinstance(case.get("scene_spec"), dict), "SCENE_SPEC_MISSING")
        require(type(case.get("pixels")) is int and case["pixels"] > 0
                and type(case.get("workers")) is int and case["workers"] > 0
                and type(case.get("triangles")) is int and case["triangles"] >= 0,
                "SCENE_SIZE_INVALID")
        samples = case.get("samples_ms")
        medians = case.get("median_frame_ms")
        require(isinstance(samples, dict) and isinstance(medians, dict)
                and "tiles" in samples and "tiles" in medians
                and samples.keys() == medians.keys(), "TIMING_MODES_INVALID")
        for label, series in samples.items():
            require(isinstance(label, str) and bool(label)
                    and isinstance(series, list) and len(series) >= MIN_REPEATS
                    and len(series) == case.get("repeats")
                    and all(_finite_positive(value) for value in series),
                    "TIMING_SAMPLES_INVALID")
            measured = statistics.median(series)
            reported = medians[label]
            require(_finite_positive(reported)
                    and math.isclose(measured, reported, rel_tol=1e-9, abs_tol=1e-9),
                    "TIMING_MEDIAN_INCONSISTENT")
        seen[case["scene"]] = case
    return seen


def compare(baseline: dict, candidate: dict) -> dict:
    """Compare raw, full-frame observations without declaring a causal gain."""
    before = audit(baseline)
    after = audit(candidate)
    require(before.keys() == after.keys(), "SCENE_SET_CHANGED")
    for key in ("benchmark_source_sha256", "fixture_source_sha256",
                "python", "numpy", "os", "environment"):
        require(baseline[key] == candidate[key], "ENVIRONMENT_OR_HARNESS_CHANGED:" + key)
    old_sources = baseline["source_paths_sha256"]
    new_sources = candidate["source_paths_sha256"]
    require(old_sources.keys() == new_sources.keys(), "SOURCE_SET_CHANGED")
    # Different implementation hashes are allowed and displayed, never hidden.
    changed_paths = sorted(p for p in old_sources if old_sources[p] != new_sources[p])
    results = []
    for name in sorted(before):
        old, new = before[name], after[name]
        for key in ("scene_spec", "pixels", "workers", "triangles", "image_sha256"):
            require(old[key] == new[key], "SCENE_OR_FRAME_CHANGED:" + name + ":" + key)
        require(old["samples_ms"].keys() == new["samples_ms"].keys(),
                "SHADING_MODES_CHANGED:" + name)
        for mode in sorted(old["samples_ms"]):
            a = old["samples_ms"][mode]
            b = new["samples_ms"][mode]
            med_a = statistics.median(a)
            med_b = statistics.median(b)
            results.append({
                "scene": name,
                "mode": mode,
                "baseline_median_ms": med_a,
                "candidate_median_ms": med_b,
                "baseline_p95_ms": _percentile(a, .95),
                "candidate_p95_ms": _percentile(b, .95),
                "baseline_mad_ms": statistics.median(abs(x - med_a) for x in a),
                "candidate_mad_ms": statistics.median(abs(x - med_b) for x in b),
                "descriptive_ratio_baseline_over_candidate": med_a / med_b,
                "samples_baseline": len(a),
                "samples_candidate": len(b),
            })
    return {
        "protocol": PROTOCOL,
        "status": "COMPARABLE_OBSERVATIONS_NO_SPEEDUP_CERTIFICATION",
        "baseline_revision": baseline["checkout"]["head"],
        "candidate_revision": candidate["checkout"]["head"],
        "changed_tracked_source_paths": changed_paths,
        "same_source_hashes": not changed_paths,
        "full_frame_rgba_depth_parity": True,
        "gpu_parity_established": False,
        "independent_replay_performed": False,
        "causal_speedup_established": False,
        "note": "Separate benchmark sessions are NOT paired A/B runs. Ratios are descriptive; "
                "runner stability and independent rerender must be checked before promotion.",
        "results": results,
    }


def _load(path: Path) -> tuple[dict, str]:
    require(path.is_file() and path.stat().st_size <= MAX_RECEIPT_BYTES, "RECEIPT_SIZE_INVALID")
    raw = path.read_bytes()
    require(len(raw) <= MAX_RECEIPT_BYTES, "RECEIPT_SIZE_INVALID")
    try:
        parsed = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise EvidenceRejected("RECEIPT_JSON_INVALID") from exc
    require(isinstance(parsed, dict), "RECEIPT_OBJECT_INVALID")
    return parsed, hashlib.sha256(raw).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (args.output.resolve() == args.baseline.resolve()
            or args.output.resolve() == args.candidate.resolve()):
        parser.error("output cannot overwrite an input evidence file")
    try:
        before, before_hash = _load(args.baseline)
        after, after_hash = _load(args.candidate)
        result = compare(before, after)
        result["input_receipts_sha256"] = {"baseline": before_hash, "candidate": after_hash}
    except (EvidenceRejected, OSError) as exc:
        print("E2E_EVIDENCE_REJECTED:" + str(exc), file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("E2E_EVIDENCE_COMPARABLE_NOT_CERTIFIED:" + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
