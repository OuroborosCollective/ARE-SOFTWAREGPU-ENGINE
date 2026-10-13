"""Offline analysis of real ARE CPU benchmark receipts; never a renderer control path.

Default mode is pure-stdlib, weight-free per-plan median baseline.
TabFM regression is strictly opt-in and subject to separate weight licensing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time

SOURCE_PROTOCOL = "are.native-raster-surface-plan-metrics.v1"
OUTPUT_PROTOCOL = "are.tabfm.offline-research.v1"
UPSTREAM_SHA = "fbb665569425fd2f490c6576b3af967876fe11ff"
FEATURES = ("triangles", "pixels", "workers", "plan")
MAX_INPUT_BYTES = 2_000_000
MAX_TABFM_CONTEXT = 100


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("NON_NUMERIC_" + field)
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("NON_POSITIVE_OR_NONFINITE_" + field)
    return number


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


def load_real_receipt(path):
    """Validate real recorded timings and extract only pre-execution features."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("RECEIPT_MISSING_OR_TOO_LARGE")
    raw = path.read_bytes()
    receipt = json.loads(raw)
    if not isinstance(receipt, dict) or receipt.get("protocol") != SOURCE_PROTOCOL:
        raise ValueError("RECEIPT_PROTOCOL")
    source_sha = receipt.get("source_artifact_sha256")
    if not isinstance(source_sha, str) or len(source_sha) != 64 or any(
            c not in "0123456789abcdef" for c in source_sha):
        raise ValueError("SOURCE_RECEIPT_HASH")
    if not isinstance(receipt.get("source_paths_sha256"), dict):
        raise ValueError("SOURCE_PATH_HASHES_MISSING")
    results = receipt.get("results")
    if not isinstance(results, list) or not 3 <= len(results) <= 100:
        raise ValueError("SCENE_COUNT")
    scenes = set()
    plan_set = None
    rows = []
    for scene in results:
        if not isinstance(scene, dict):
            raise ValueError("SCENE_SCHEMA")
        name = scene.get("scene")
        if not isinstance(name, str) or not name or name in scenes:
            raise ValueError("SCENE_DUPLICATE_OR_MISSING")
        scenes.add(name)
        if scene.get("byte_identical") is not True:
            raise ValueError("RENDER_PARITY_REQUIRED")
        if scene.get("gpu_parity_established") is not False:
            raise ValueError("GPU_PARITY_CLAIM_REJECTED")
        triangles = _number(scene.get("triangles"), "triangles")
        pixels = _number(scene.get("pixels"), "pixels")
        workers = _number(scene.get("workers"), "workers")
        stats = scene.get("stats_ms")
        samples = scene.get("samples_ms")
        if not isinstance(stats, dict) or not isinstance(samples, dict):
            raise ValueError("TIMINGS_MISSING")
        if not stats or set(stats) != set(samples):
            raise ValueError("PLAN_SAMPLES_MISMATCH")
        if plan_set is None:
            plan_set = set(stats)
        if set(stats) != plan_set:
            raise ValueError("UNBALANCED_SCENE_PLANS")
        for plan in sorted(stats):
            if not isinstance(plan, str) or len(plan) > 64 or not plan or any(
                    c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in plan):
                raise ValueError("PLAN_NAME_INVALID")
            values = samples[plan]
            detail = stats[plan]
            if not isinstance(values, list) or not 5 <= len(values) <= 30:
                raise ValueError("RAW_SAMPLES_REQUIRED")
            if not isinstance(detail, dict) or detail.get("n") != len(values):
                raise ValueError("SAMPLE_COUNT_MISMATCH")
            checked = [_number(value, "sample_ms") for value in values]
            claimed = _number(detail.get("median"), "median_ms")
            if not math.isclose(statistics.median(checked), claimed,
                                rel_tol=1e-8, abs_tol=1e-5):
                raise ValueError("MEDIAN_MISMATCH")
            rows.append({"scene": name, "triangles": triangles,
                         "pixels": pixels, "workers": workers,
                         "plan": plan, "median_ms": claimed})
    rows.sort(key=lambda r: (r["scene"], r["plan"]))
    return {"rows": rows, "source_sha256": _sha(raw),
            "source_artifact_sha256": source_sha,
            "rows_sha256": _sha(_canonical(rows)),
            "scenes": sorted(scenes), "plans": sorted(plan_set)}


def _features(rows):
    return [{name: row[name] for name in FEATURES} for row in rows]


def _baseline(train, test):
    by_plan = {}
    for row in train:
        by_plan.setdefault(row["plan"], []).append(row["median_ms"])
    if any(row["plan"] not in by_plan for row in test):
        raise ValueError("UNKNOWN_TEST_PLAN")
    return [statistics.median(by_plan[row["plan"]]) for row in test]


def _tabfm_predict(model, train, test):
    # Import is delayed until *after* the explicit noncommercial rights guard.
    import numpy as np
    import pandas as pd
    from tabfm import TabFMRegressor
    reg = TabFMRegressor(model=model, max_num_features=len(FEATURES),
                         max_num_rows=MAX_TABFM_CONTEXT, n_estimators=1,
                         random_state=1234)
    reg.fit(pd.DataFrame(_features(train), columns=FEATURES),
            np.asarray([r["median_ms"] for r in train], dtype=float))
    return list(reg.predict(pd.DataFrame(_features(test), columns=FEATURES)))


def _metrics(pairs):
    if not pairs:
        raise ValueError("NO_PREDICTIONS")
    errors = [abs(actual - predicted) for actual, predicted in pairs]
    smape = [200 * abs(actual - predicted) / (actual + predicted)
             for actual, predicted in pairs]
    return {"n": len(pairs), "mae_ms": statistics.mean(errors),
            "median_ae_ms": statistics.median(errors),
            "smape_percent": statistics.mean(smape)}


def evaluate(path, mode="baseline", confirm_research_rights=False):
    """Leave-one-whole-scene-out evaluation; neither trains nor tunes the renderer.

    Confirming is an explicit assertion of rights, not a grant of rights.
    """
    if mode not in ("baseline", "tabfm"):
        raise ValueError("EVALUATION_MODE")
    if mode == "tabfm" and not (confirm_research_rights and
            os.getenv("ARE_TABFM_NONCOMMERCIAL_RESEARCH") == "1"):
        raise PermissionError("TABFM_NONCOMMERCIAL_WEIGHTS_NOT_AUTHORIZED")
    data = load_real_receipt(path)
    rows = data["rows"]
    scenes = data["scenes"]
    if mode == "tabfm" and len(rows) - len(data["plans"]) > MAX_TABFM_CONTEXT:
        raise ValueError("TABFM_CONTEXT_WOULD_SAMPLE_SILENTLY")

    weights = None
    load_seconds = None
    if mode == "tabfm":
        # Google source is Apache-2.0; these weights are *not*: never on CI by default.
        from tabfm import tabfm_v1_0_0_pytorch
        before = time.perf_counter()
        weights = tabfm_v1_0_0_pytorch.load(model_type="regression")
        load_seconds = time.perf_counter() - before

    folds = []
    all_pairs = []
    for held_out in scenes:
        train = [row for row in rows if row["scene"] != held_out]
        test = [row for row in rows if row["scene"] == held_out]
        if not train or not test:
            raise ValueError("EMPTY_FOLD")
        train_scenes = sorted({row["scene"] for row in train})
        if held_out in train_scenes:
            raise ValueError("SCENE_LEAKAGE")
        started = time.perf_counter()
        predicted = (_baseline(train, test) if mode == "baseline"
                     else _tabfm_predict(weights, train, test))
        elapsed = time.perf_counter() - started
        if len(predicted) != len(test):
            raise ValueError("PREDICTION_COUNT")
        pairs = []
        entries = []
        for row, value in zip(test, predicted):
            forecast = _number(value, "prediction_ms")
            actual = row["median_ms"]
            pairs.append((actual, forecast))
            entries.append({"plan": row["plan"], "actual_ms": actual,
                            "predicted_ms": forecast})
        all_pairs.extend(pairs)
        fold = {"held_out_scene": held_out, "training_scenes": train_scenes,
                "n_training": len(train), "metrics": _metrics(pairs),
                "predictions": entries}
        if mode == "tabfm":
            fold["fit_predict_seconds"] = elapsed
        folds.append(fold)

    report = {"protocol": OUTPUT_PROTOCOL, "status": "PASS",
              "mode": mode, "features": list(FEATURES),
              "source_sha256": data["source_sha256"],
              "source_artifact_sha256": data["source_artifact_sha256"],
              "rows_sha256": data["rows_sha256"],
              "n_scenes": len(scenes), "n_rows": len(rows),
              "plans": data["plans"], "folds": folds,
              "overall": _metrics(all_pairs),
              "tabfm_upstream_sha": UPSTREAM_SHA if mode == "tabfm" else None,
              "model_weight_license": "tabfm-non-commercial-v1.0" if mode == "tabfm" else None,
              "weight_download_requested": mode == "tabfm",
              "model_load_seconds": load_seconds,
              "limitations": [
                  "Five existing scene families only; sample size is not representative",
                  "Historical CPU receipt, not fresh frame measurements",
                  "Pre-execution features omit triangle coverage and shader complexity",
                  "Full scenes are held out; no random row-wise leakage",
                  "Offline research only; no renderer policy or live runtime changes",
                  "CPU-to-CPU results do not establish hardware GPU parity",
                  "Historical source hashes are provenance, not current checkout parity"
              ]}
    report["report_sha256"] = _sha(_canonical(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="evidence/native-raster-surface-plan-metrics-v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=["baseline", "tabfm"], default="baseline")
    parser.add_argument("--confirm-research-rights", action="store_true",
                        help="Assert separate authorization to use noncommercial weights")
    args = parser.parse_args(argv)
    result = evaluate(args.input, args.mode, args.confirm_research_rights)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2,
                                 ensure_ascii=False, allow_nan=False) + "\n",
                      encoding="utf-8")
    print(json.dumps({"status": result["status"], "mode": result["mode"],
                      "n_rows": result["n_rows"], "overall": result["overall"],
                      "report_sha256": result["report_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
