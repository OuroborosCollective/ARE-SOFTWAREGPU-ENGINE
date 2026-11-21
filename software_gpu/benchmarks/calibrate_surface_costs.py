"""Offline, source-bound empirical cost buckets for the existing SurfacePlanner.

No wall clock, random input, I/O, or provider call is consulted by replay.
Unknown buckets or unproven holdouts return None (the caller keeps `tiles`).
This does not add a second rasterizer, change the default, or claim FPS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys

PROTOCOL = "are.surface-cost-calibration.v1"
BENCHMARK_PROTOCOL = "are.surface-plan-benchmark.v1"
MIN_PAIRS = 15
MODE_FLAGS = {
    "abl-noscan-scalar": {"scan": False, "batch": False},
    "abl-noscan-batch": {"scan": False, "batch": True},
    "abl-scan-scalar": {"scan": True, "batch": False},
    "abl-scan-batch": {"scan": True, "batch": True},
}
BASELINE = "abl-noscan-scalar"


class CostEvidenceError(ValueError):
    """A source, timing, parity, holdout or policy admission gate failed."""


def _need(ok: bool, reason: str):
    if not ok:
        raise CostEvidenceError("SURFACE_COST_" + reason)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, ensure_ascii=True).encode("utf-8")


def _percentile(values, q):
    values = sorted(values)
    position = (len(values) - 1) * q
    left = int(position)
    upper = min(len(values) - 1, left + 1)
    return values[left] + (values[upper] - values[left]) * (position - left)


def _summary(values):
    median = statistics.median(values)
    return {"n": len(values), "median": float(median),
            "iqr": float(_percentile(values, .75) - _percentile(values, .25)),
            "mad": float(statistics.median([abs(v - median) for v in values]))}


def _band(triangles: int, bbox_samples: int) -> str:
    _need(type(triangles) is int and triangles > 0, "FEATURE_TRIANGLES")
    _need(type(bbox_samples) is int and bbox_samples >= 0, "FEATURE_BBOX")
    density = bbox_samples // triangles
    tgroup = "tiny" if triangles <= 8 else "middle" if triangles <= 256 else "dense"
    coverage = "small" if density < 64 else "medium" if density < 512 else "large"
    return tgroup + ":" + coverage


def _check_receipt(doc: dict, root: Path, revision: str):
    _need(type(doc) is dict and doc.get("protocol") == BENCHMARK_PROTOCOL,
          "BENCHMARK_PROTOCOL")
    _need(doc.get("activation") == "EXPLICIT_OPT_IN_ONLY", "BENCHMARK_ACTIVATION")
    _need(type(revision) is str and len(revision) == 40 and
          all(c in "0123456789abcdef" for c in revision), "SOURCE_REVISION")
    sources = doc.get("source_paths_sha256")
    _need(type(sources) is dict and len(sources) >= 10, "SOURCE_MANIFEST")
    for name, digest in sorted(sources.items()):
        p = Path(name)
        _need(type(name) is str and type(digest) is str and len(digest) == 64 and
              all(c in "0123456789abcdef" for c in digest) and not p.is_absolute()
              and ".." not in p.parts and p.suffix == ".py", "SOURCE_MANIFEST")
        source = (root / p).resolve()
        _need(source.is_relative_to(root.resolve()) and source.is_file(), "SOURCE_MISSING")
        _need(_sha(source.read_bytes()) == digest, "SOURCE_SHA_MISMATCH")
    env = doc.get("environment")
    _need(type(env) is dict and bool(env.get("cpu_model"))
          and type(env.get("affinity_cpus")) in (int, type(None))
          and "numpy_build" in env and "thread_env" in env,
          "CPU_PROVENANCE")
    for field in ("python", "os", "numpy"):
        _need(type(doc.get(field)) is str and bool(doc[field]), "CPU_PROVENANCE")
    cases = doc.get("results")
    _need(type(cases) is list and bool(cases), "SCENES_MISSING")
    seen = set()
    for case in cases:
        _need(type(case) is dict and type(case.get("scene")) is str
              and bool(case["scene"]) and case["scene"] not in seen, "SCENES_DUPLICATED")
        seen.add(case["scene"])
        n = case.get("repeats")
        _need(type(n) is int and MIN_PAIRS <= n <= 30, "PAIRED_RUN_COUNT")
        _need(type(case.get("pixels")) is int and 32 <= case["pixels"] <= 1024
              and type(case.get("workers")) is int and case["workers"] >= 1,
              "SCENE_DIMENSIONS")
        _need(case.get("byte_identical") is True, "COLOR_DEPTH_PARITY")
        for field in ("image_sha256", "color_sha256", "depth_sha256"):
            digest = case.get(field)
            _need(type(digest) is str and len(digest) == 64 and
                  all(ch in "0123456789abcdef" for ch in digest), "COLOR_DEPTH_DIGEST")
        modes = case.get("samples_ms")
        plans = case.get("plans")
        _need(type(modes) is dict and type(plans) is dict, "ABLATION_MISSING")
        for mode, flags in MODE_FLAGS.items():
            values = modes.get(mode)
            _need(type(values) is list and len(values) == n and all(
                type(v) in (int, float) and math.isfinite(v) and v > 0 for v in values),
                "PAIRED_RAW_TIMES")
            plan = plans.get(mode)
            _need(type(plan) is dict and plan.get("decision") == "planned"
                  and type(plan.get("counts")) is dict and
                  plan.get("draw_min_bbox_samples_per_triangle") == 0,
                  "ABLATION_NOT_APPLIED")
            _need(plan.get("scan_min_samples") == (64 if flags["scan"] else sys.maxsize)
                  and plan.get("batch_min_samples") == (8 if flags["batch"] else sys.maxsize),
                  "ABLATION_NOT_APPLIED")
            if not flags["batch"]:
                _need(plan["counts"].get("batch_fragment_calls") == 0 and
                      plan["counts"].get("batch_fragment_samples") == 0,
                      "SCALAR_NOT_APPLIED")
            if not flags["scan"]:
                _need(plan["counts"].get("corner_edge_evaluations") == 0,
                      "NOSCAN_NOT_APPLIED")
            _need(type(plan.get("estimated_bbox_samples")) is int and
                  type(plan.get("triangle_count")) is int and
                  plan["triangle_count"] == case.get("triangles"), "PRE_DRAW_FEATURES")
            _band(plan["triangle_count"], plan["estimated_bbox_samples"])
            if "stats_ms" in case:
                stat = case["stats_ms"].get(mode)
                _need(type(stat) is dict and all(
                    math.isclose(stat.get(key, -1), value, abs_tol=1e-6, rel_tol=1e-6)
                    for key, value in _summary(values).items()), "TIMING_STATS_MISMATCH")
    return cases


def validate_benchmark(receipt: dict, root: Path, revision: str):
    """Verify one SHA-bound 15-pair receipt without claiming an independent draw."""
    return _check_receipt(receipt, Path(root), revision)


def _case_band(case):
    plan = case["plans"][BASELINE]
    return _band(plan["triangle_count"], plan["estimated_bbox_samples"])


def _ratios(cases, mode):
    return [base / trial
            for case in cases
            for base, trial in zip(case["samples_ms"][BASELINE], case["samples_ms"][mode])]


def calibrate(training: dict, holdout: dict, root: Path, revision: str) -> dict:
    """Produce deterministic measured-cost buckets; only proven buckets can replay.

    Inputs must be independently recorded 15-pair, byte-identical real draws.
    Validation is NOT an independent rerender; the CI benchmark supplies that.
    """
    root = Path(root)
    train = _check_receipt(training, root, revision)
    test = _check_receipt(holdout, root, revision)
    for field in ("source_paths_sha256", "environment", "python", "numpy", "os"):
        _need(training[field] == holdout[field], "HOLDOUT_ENVIRONMENT_MISMATCH")
    _need(not ({case["scene"] for case in train} & {case["scene"] for case in test}),
          "HOLDOUT_OVERLAPS_TRAINING")
    train_specs = {_sha(_canonical(case["scene_spec"])) for case in train}
    _need(not (train_specs & {_sha(_canonical(case["scene_spec"])) for case in test}),
          "HOLDOUT_SAME_GEOMETRY")
    groups = sorted({_case_band(case) for case in train})
    profiles = {}
    enabled = {}
    for band in groups:
        training_rows = [case for case in train if _case_band(case) == band]
        holdout_rows = [case for case in test if _case_band(case) == band]
        costs = {mode: _summary([v / max(1, case["plans"][BASELINE]["estimated_bbox_samples"])
                                 for case in training_rows for v in case["samples_ms"][mode]])["median"]
                 for mode in MODE_FLAGS}
        ranked = [(statistics.median(_ratios(training_rows, mode)), mode)
                  for mode in MODE_FLAGS if mode != BASELINE]
        rank, candidate = max(ranked, key=lambda item: (item[0], item[1]))
        holdout_ratios = _ratios(holdout_rows, candidate) if holdout_rows else []
        holding = _summary(holdout_ratios) if holdout_ratios else None
        passed = bool(holdout_rows and rank >= 1.08 and holding["median"] >= 1.05
                      and _percentile(holdout_ratios, .25) >= 1.0
                      and all(case["byte_identical"] for case in holdout_rows))
        profiles[band] = {
            "weight_units": "measured_ms_per_estimated_bbox_sample",
            "weights": costs, "train_scenes": sorted(c["scene"] for c in training_rows),
            "holdout_scenes": sorted(c["scene"] for c in holdout_rows),
            "candidate": candidate, "train_paired_median": float(rank),
            "holdout_paired": holding,
            "status": "holdout_validated" if passed else "reference_only",
        }
        if passed:
            enabled[band] = candidate
    body = {
        "protocol": PROTOCOL, "source_revision": revision,
        "source_paths_sha256": training["source_paths_sha256"],
        "training_receipt_sha256": _sha(_canonical(training)),
        "holdout_receipt_sha256": _sha(_canonical(holdout)),
        "cpu_environment": {key: training[key] for key in ("python", "numpy", "os")},
        "environment": training["environment"],
        "policy_basis": "same-vertex-color-shader-4-factorial-v1",
        "min_interleaved_pairs": MIN_PAIRS,
        "min_train_median_ratio": 1.08,
        "min_holdout_median_ratio": 1.05,
        "min_holdout_first_quartile_ratio": 1.0,
        "buckets": profiles, "validated_routes": enabled,
        "default_unchanged": True, "runtime_admission": "explicit_opt_in_only",
        "general_fps_claim": False,
    }
    return dict(body, model_sha256=_sha(_canonical(body)))


def validate_model(model):
    _need(type(model) is dict and model.get("protocol") == PROTOCOL
          and model.get("policy_basis") == "same-vertex-color-shader-4-factorial-v1"
          and model.get("default_unchanged") is True
          and model.get("runtime_admission") == "explicit_opt_in_only"
          and type(model.get("validated_routes")) is dict,
          "MODEL_CONTRACT")
    body = {key: value for key, value in model.items() if key != "model_sha256"}
    _need(_sha(_canonical(body)) == model.get("model_sha256"), "MODEL_DIGEST")
    _need(all(type(band) is str and mode in MODE_FLAGS and mode != BASELINE
              and model.get("buckets", {}).get(band, {}).get("status") == "holdout_validated"
              and model["buckets"][band].get("candidate") == mode
              for band, mode in model["validated_routes"].items()), "MODEL_ROUTES")
    return model


def select_replay_policy(model, *, triangles: int, bbox_samples: int, shader,
                         expected_source_revision: str):
    """Pure explicit opt-in: return existing SurfacePlanPolicy or None.

    A None result means use unchanged backend='tiles'. No timing, IO, randomness
    or provider lookup is performed here; all evidence is frozen before the draw.
    """
    validate_model(model)
    _need(expected_source_revision == model["source_revision"], "STALE_SOURCE_REVISION")
    bucket = _band(triangles, bbox_samples)
    mode = model["validated_routes"].get(bucket)
    if mode is None:
        return None
    from software_gpu.graphics.surface_plan import SurfacePlanPolicy, equivalent_batch
    if equivalent_batch(shader) is None:
        return None
    flags = MODE_FLAGS[mode]
    return SurfacePlanPolicy(
        scan_min_samples=64 if flags["scan"] else sys.maxsize,
        batch_min_samples=8 if flags["batch"] else sys.maxsize,
        draw_min_bbox_samples_per_triangle=0,
        selection="fixed", name="cost-v1-" + model["model_sha256"][:8] + "-" + mode,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", required=True, type=Path)
    parser.add_argument("--holdout", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        actual = subprocess.check_output(
            ["git", "-C", str(args.root), "rev-parse", "HEAD"],
            text=True, timeout=10).strip()
        _need(args.source_revision == actual, "SOURCE_REVISION_MISMATCH")
        training = json.loads(args.training.read_text(encoding="utf-8"))
        holdout = json.loads(args.holdout.read_text(encoding="utf-8"))
        model = calibrate(training, holdout, args.root, actual)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(model, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, "SURFACE_COST_CALIBRATION_REFUSED:" + str(error) + "\n")
    print(json.dumps({"status": "OFFLINE_COST_MODEL_WRITTEN", "sha256": model["model_sha256"],
                      "validated_buckets": sorted(model["validated_routes"])}))


if __name__ == "__main__":
    main()
