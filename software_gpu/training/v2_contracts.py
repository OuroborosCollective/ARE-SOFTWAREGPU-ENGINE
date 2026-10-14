"""Fail-closed PyTorch V2 training planning, checkpoints and quality gates.

This module has no network, billing, GPU execution or tensor allocations.
It never trains or releases a model. Runtime work is separately authorized.
"""
from __future__ import annotations
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

BASE = "Qwen/Qwen2.5-0.5B-Instruct"
REV = "7ae557604adf67be50417f59c2c2f167def9a775"
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
REQUIRED = ("optimizer.pt", "scheduler.pt", "rng_state.pth", "trainer_state.json",
            "adapter_model.safetensors")
THREADS = [2, 4, 6, 8]
RANKS = (8, 16, 32)
LRS = ("0.00005", "0.0001", "0.0002")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _pins(settings, renderer_sha):
    if not isinstance(settings, dict) or not isinstance(renderer_sha, str) or not HEX40.fullmatch(renderer_sha):
        raise ValueError("V2_PIN_OR_POLICY")
    keys = ("code_revision", "evidence_revision", "atomic_revision",
            "bench_revision", "base_revision")
    if any(not isinstance(settings.get(k), str) or not HEX40.fullmatch(settings[k]) for k in keys):
        raise ValueError("V2_PIN_OR_POLICY")
    if (settings.get("base_model"), settings["base_revision"]) != (BASE, REV):
        raise ValueError("V2_PIN_OR_POLICY")
    return {key: settings[key] for key in ("base_model", *keys)}


def profile_threads(options):
    if not isinstance(options, (list, tuple)) or not options or list(options) != sorted(set(options)):
        raise ValueError("V2_THREADS")
    if any(type(t) is not int or t not in THREADS for t in options):
        raise ValueError("V2_THREADS")
    return list(options)


def build_sweep(settings, renderer_sha):
    pins = _pins(settings, renderer_sha)
    candidates = [
        {"id": f"r{rank}-lr{lr}", "rank": rank, "learning_rate": lr, "seed": 42,
         "epochs": 1, "max_length": 8192, "gradient_accumulation_steps": 4,
         "device": "cpu", "status": "plan-only", "training_started": False}
        for rank in RANKS for lr in LRS
    ]
    return {"protocol": "are.miha.train-plan.v2", "renderer_sha": renderer_sha,
            "pins": pins, "candidates": candidates, "thread_trials": THREADS[:],
            "training_started": False, "gpu_allowed": False, "release_accepted": False}


def select_experiment(plan, experiment_id):
    if plan.get("protocol") != "are.miha.train-plan.v2":
        raise ValueError("V2_UNKNOWN_EXPERIMENT")
    matches = [candidate for candidate in plan["candidates"] if candidate["id"] == experiment_id]
    if len(matches) != 1:
        raise ValueError("V2_UNKNOWN_EXPERIMENT")
    return matches[0]


def training_identity(settings, dataset_sha256, renderer_sha, candidate, device, threads):
    pins = _pins(settings, renderer_sha)
    if not isinstance(dataset_sha256, str) or not HEX64.fullmatch(dataset_sha256):
        raise ValueError("V2_PIN_OR_POLICY")
    if device != "cpu" or threads not in THREADS or type(threads) is not int:
        raise ValueError("V2_PIN_OR_POLICY")
    if candidate.get("rank") not in RANKS or candidate.get("learning_rate") not in LRS:
        raise ValueError("V2_PIN_OR_POLICY")
    return {**pins, "dataset_sha256": dataset_sha256, "renderer_sha": renderer_sha,
            "rank": candidate["rank"], "learning_rate": candidate["learning_rate"],
            "seed": candidate["seed"], "device": device, "threads": threads,
            "max_length": candidate["max_length"], "epochs": candidate["epochs"],
            "gradient_accumulation_steps": candidate["gradient_accumulation_steps"]}


def _files(path):
    found = {}
    for name in REQUIRED:
        file = path / name
        if not file.is_file() or file.is_symlink():
            raise ValueError("V2_CHECKPOINT_MISSING")
        found[name] = _sha(file.read_bytes())
    return found


def _step(path):
    try:
        step = int(path.name.removeprefix("checkpoint-"))
        doc = json.loads((path / "trainer_state.json").read_text())
    except (ValueError, OSError, json.JSONDecodeError):
        raise ValueError("V2_CHECKPOINT_STEP") from None
    if not path.name.startswith("checkpoint-") or step < 1 or type(doc.get("global_step")) is not int or doc["global_step"] != step:
        raise ValueError("V2_CHECKPOINT_STEP")
    return step


def seal_checkpoint(path, identity):
    path = Path(path)
    files = _files(path)
    step = _step(path)
    receipt = {"protocol": "are.miha.checkpoint.v2", "identity": identity,
               "step": step, "files_sha256": files, "resume_accepted": False}
    receipt["sha256"] = _sha(_json(receipt))
    dest = path / "v2_resume_receipt.json"
    with dest.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return receipt


def verify_checkpoint(path, identity):
    path = Path(path)
    receipt_path = path / "v2_resume_receipt.json"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError("V2_CHECKPOINT_MISSING")
    try:
        receipt = json.loads(receipt_path.read_text())
    except (OSError, ValueError):
        raise ValueError("V2_CHECKPOINT_HASH") from None
    if receipt.get("sha256") != _sha(_json({k: v for k, v in receipt.items() if k != "sha256"})):
        raise ValueError("V2_CHECKPOINT_HASH")
    if receipt.get("protocol") != "are.miha.checkpoint.v2" or receipt.get("identity") != identity:
        raise ValueError("V2_CHECKPOINT_IDENTITY")
    if receipt.get("step") != _step(path):
        raise ValueError("V2_CHECKPOINT_STEP")
    if receipt.get("files_sha256") != _files(path):
        raise ValueError("V2_CHECKPOINT_HASH")
    return True


def quality_gate(report, expected_ids, bench_revision, minimum=0.75):
    if not isinstance(report, dict) or report.get("benchmark_revision") != bench_revision:
        raise ValueError("V2_HOLDOUT_IDENTITY")
    if not isinstance(bench_revision, str) or not HEX40.fullmatch(bench_revision):
        raise ValueError("V2_HOLDOUT_IDENTITY")
    ids = [row.get("id") for row in report.get("candidate", {}).get("records", [])]
    if len(ids) != len(expected_ids) or set(ids) != set(expected_ids) or len(set(ids)) != len(ids):
        raise ValueError("V2_HOLDOUT_INCOMPLETE")
    candidate = report["candidate"]["summary"]
    passed = (report.get("adapter_reload_verified") is True
              and all(row.get("parse_ok") is True for row in report["candidate"]["records"])
              and candidate.get("parse_fail") == 0
              and not report.get("regressions")
              and candidate.get("allowed_source_compliance") == 1
              and candidate.get("forbidden_source_compliance") == 1
              and isinstance(candidate.get("score"), (int, float))
              and candidate["score"] >= minimum
              and candidate["score"] >= report.get("baseline", {}).get("summary", {}).get("score", float("inf")))
    return {"gates_passed": bool(passed), "release_accepted": False,
            "status": "eligible_for_separate_verified_release" if passed else "FAIL_CLOSED"}


def require_gpu_research_gate(policy, allow, visible_devices, bf16_supported, vram_bytes):
    if not isinstance(policy, dict) or policy.get("gpu_allowed") is not True:
        raise ValueError("V2_GPU_POLICY_DENIED")
    if allow is not True:
        raise ValueError("V2_GPU_EXPLICIT_OPT_IN")
    if type(visible_devices) is not int or visible_devices < 1 or bf16_supported is not True or type(vram_bytes) is not int or vram_bytes < 16 * 1024**3:
        raise ValueError("V2_GPU_RESOURCE_GATE")
    return True
