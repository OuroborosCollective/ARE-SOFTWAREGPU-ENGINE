#!/usr/bin/env python3
"""Opt-in MIHA V2 planning, real PyTorch CPU profiling and evidence gates.

This tool never starts model training, GPU sessions or Hugging Face uploads.
Its CPU matrix microprofile measures a real PyTorch backward, not MIHA quality.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import statistics
import time

from software_gpu.training.v2_contracts import (
    build_sweep, profile_threads, quality_gate, require_gpu_research_gate,
    training_identity, select_experiment, verify_checkpoint,
)


def emit(path, result):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    receipt = dict(result, sha256=hashlib.sha256(raw).hexdigest())
    with target.open("x", encoding="utf-8") as fp:
        json.dump(receipt, fp, sort_keys=True, indent=2)
        fp.write("\n")
    if json.loads(target.read_text()) != receipt:
        raise RuntimeError("V2_READBACK_FAILURE")
    print(json.dumps({"receipt": str(target), "sha256": receipt["sha256"]}))
    return receipt


def cpu_profile(threads, width=256, repeats=15):
    import torch
    from torch.profiler import ProfilerActivity, profile
    if width not in (256, 512) or repeats != 15:
        raise ValueError("V2_PROFILE_BOUNDS")
    report = {"protocol": "are.miha.cpu-microprofile.v1", "status": "RESEARCH_ONLY",
              "torch": torch.__version__, "width": width, "repeats": repeats,
              "limits": ["real CPU torch matmul/autograd, no model training",
                         "not a MIHA LoRA speedup", "no GPU usage"],
              "profiles": []}
    for count in profile_threads(threads):
        torch.set_num_threads(count)
        torch.manual_seed(42)
        weight = torch.randn(width, width, device="cpu", requires_grad=True)
        values = torch.randn(width, width, device="cpu")
        def step():
            weight.grad = None
            loss = ((values @ weight) ** 2).mean()
            loss.backward()
            if not torch.isfinite(loss).item():
                raise ValueError("V2_NONFINITE_CPU_LOSS")
            return float(loss.item())
        for _ in range(3):
            step()
        times = []
        with profile(activities=[ProfilerActivity.CPU], record_shapes=True,
                     profile_memory=True) as prof:
            for _ in range(repeats):
                started = time.perf_counter_ns()
                step()
                times.append((time.perf_counter_ns() - started) / 1e6)
        report["profiles"].append({
            "threads": count, "raw_ms": times,
            "median_ms": statistics.median(times),
            "max_ms": max(times), "min_ms": min(times),
            "peak_process_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "top_cpu_ops": [
                {"op": op.key, "self_cpu_time_us": op.self_cpu_time_total, "count": op.count}
                for op in sorted(prof.key_averages(), key=lambda x: x.self_cpu_time_total, reverse=True)[:8]
            ]})
    return report


def main():
    cli = argparse.ArgumentParser()
    sub = cli.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--config", default="fixtures/miha/training.json")
    p.add_argument("--renderer-sha", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("cpu-profile")
    p.add_argument("--threads", type=int, nargs="+", default=[2,4,6,8])
    p.add_argument("--width", type=int, default=256)
    p.add_argument("--output", required=True)
    p = sub.add_parser("verify-checkpoint")
    p.add_argument("--config", default="fixtures/miha/training.json")
    p.add_argument("--renderer-sha", required=True)
    p.add_argument("--dataset-sha256", required=True)
    p.add_argument("--experiment-id", required=True)
    p.add_argument("--threads", type=int, required=True)
    p.add_argument("--path", required=True)
    p = sub.add_parser("quality-gate")
    p.add_argument("--report", required=True)
    p.add_argument("--expected-ids", required=True)
    p.add_argument("--bench-revision", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("gpu-preflight")
    p.add_argument("--policy", required=True)
    p.add_argument("--allow", action="store_true")
    p.add_argument("--devices", type=int, default=0)
    p.add_argument("--vram-gib", type=int, default=0)
    p.add_argument("--bf16", action="store_true")
    a = cli.parse_args()
    if a.cmd == "plan":
        emit(a.output, build_sweep(json.loads(Path(a.config).read_text()), a.renderer_sha))
    elif a.cmd == "cpu-profile":
        emit(a.output, cpu_profile(a.threads, a.width))
    elif a.cmd == "verify-checkpoint":
        settings = json.loads(Path(a.config).read_text())
        experiment = select_experiment(build_sweep(settings, a.renderer_sha), a.experiment_id)
        identity = training_identity(settings, a.dataset_sha256, a.renderer_sha,
                                     experiment, "cpu", a.threads)
        verify_checkpoint(a.path, identity)
        print("V2_CHECKPOINT_VERIFIED: integrity only, no training resumed")
    elif a.cmd == "quality-gate":
        result = quality_gate(json.loads(Path(a.report).read_text()),
                              json.loads(Path(a.expected_ids).read_text()),
                              a.bench_revision)
        emit(a.output, result)
        if not result["gates_passed"]:
            raise SystemExit(2)
    else:
        policy = json.loads(Path(a.policy).read_text())
        require_gpu_research_gate(policy, a.allow, a.devices,
                                  a.bf16, a.vram_gib * 1024**3)
        print("V2_GPU_GATE_PASS: no GPU or training started")


if __name__ == "__main__":
    main()
