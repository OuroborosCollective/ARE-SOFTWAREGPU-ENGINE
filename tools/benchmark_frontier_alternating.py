#!/usr/bin/env python3
"""Actual AB/BA native research benchmark; never a production policy selector.

Runs alternating C++17 *builds* on one GitHub-hosted CPU worker. Each child
performs its own three warmups and one timed frame (the upstream wire receipt).
No simulated timings, stubs, model inference or renderer runtime Python.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from software_gpu.research.bio_workrooms import build_bio_workrooms, run_bio_workrooms
from software_gpu.research.workrooms import descriptor, encode_request
from software_gpu.tests.test_bio_workrooms import sparse_scene
from software_gpu.tests.test_workrooms import scene_fixture

PROTOCOL = "are.bio-frontier.alternating-native-ab.v1"
VARIANTS = ("default", "static-frontier-chunks")
SOURCES = ("native/symbolic/bio_workrooms.hpp",
           "native/symbolic/bio_workrooms_main.cpp",
           "software_gpu/research/bio_workrooms.py",
           "tools/benchmark_frontier_alternating.py",
           "software_gpu/tests/test_bio_frontier_cache_ablation.py")
CASES = (("sparse64-tile1", 128, 1, sparse_scene),
         ("large4-tile16", 256, 16, scene_fixture))


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def order_for_pair(i):
    # Adjacent pairs AB then BA; exactly 15 real pairs, neither phase omitted.
    return VARIANTS if i % 2 == 0 else tuple(reversed(VARIANTS))


def source_hashes():
    return {path: digest((ROOT / path).read_bytes()) for path in SOURCES}


def positive(value):
    return type(value) in (float, int) and math.isfinite(value) and value > 0


def verify_report(report):
    """Readback integrity. This is not an independent raster/oracle rerender."""
    if not isinstance(report, dict) or report.get("protocol") != PROTOCOL or report.get("status") != "PASS":
        raise ValueError("ABBA_PROTOCOL")
    checksum = report.get("report_sha256")
    payload = {k: v for k, v in report.items() if k != "report_sha256"}
    if not isinstance(checksum, str) or checksum != digest(canonical(payload)):
        raise ValueError("ABBA_REPORT_DIGEST")
    if report.get("variants") != list(VARIANTS) or not isinstance(report.get("builds"), dict):
        raise ValueError("ABBA_VARIANTS")
    if set(report["builds"]) != set(VARIANTS):
        raise ValueError("ABBA_MISSING_BUILD")
    repeats, cases = report.get("repeats"), report.get("cases")
    workers = report.get("workers")
    if type(repeats) is not int or not 15 <= repeats <= 30 or not isinstance(cases, list):
        raise ValueError("ABBA_REPEATS")
    if not isinstance(workers, list) or not workers or len(set(workers)) != len(workers):
        raise ValueError("ABBA_WORKERS")
    if any(w not in (1, 2, 4, 8) for w in workers):
        raise ValueError("ABBA_WORKER_COUNT")
    if len(cases) != len(CASES) * len(workers):
        raise ValueError("ABBA_CASE_COUNT")
    seen = set()
    per_scene = {}
    for case in cases:
        name, w = case.get("scene"), case.get("workers")
        if (name, w) in seen or name not in {s[0] for s in CASES} or w not in workers:
            raise ValueError("ABBA_CASE_DUPLICATE")
        seen.add((name, w))
        if len(case.get("pairs", [])) != repeats:
            raise ValueError("ABBA_PAIR_COUNT")
        frame = case.get("image_depth_sha256")
        if not isinstance(frame, str) or len(frame) != 64:
            raise ValueError("ABBA_FRAME_HASH")
        if name in per_scene and per_scene[name] != frame:
            raise ValueError("ABBA_WORKER_FRAME_MISMATCH")
        per_scene[name] = frame
        default, static = [], []
        for i, p in enumerate(case["pairs"]):
            if p.get("pair") != i or p.get("order") != list(order_for_pair(i)):
                raise ValueError("ABBA_ORDER")
            samples = p.get("measured_ms")
            cpu = p.get("cpu_ms")
            if not isinstance(samples, dict) or set(samples) != set(VARIANTS):
                raise ValueError("ABBA_TIMING_MISSING")
            if not isinstance(cpu, dict) or set(cpu) != set(VARIANTS):
                raise ValueError("ABBA_CPU_TIMING_MISSING")
            if any(not positive(samples[k]) for k in VARIANTS):
                raise ValueError("ABBA_TIMING_INVALID")
            if any(type(cpu[k]) not in (int,float) or not math.isfinite(cpu[k]) or cpu[k] < 0 for k in VARIANTS):
                raise ValueError("ABBA_CPU_TIMING_INVALID")
            default.append(samples["default"])
            static.append(samples["static-frontier-chunks"])
        median_diff = statistics.median(s - d for d, s in zip(default, static))
        median_ratio = statistics.median(s / d for d, s in zip(default, static))
        if (not math.isclose(case["median_paired_delta_ms"], median_diff, abs_tol=1e-9)
            or not math.isclose(case["median_paired_static_over_default"], median_ratio, abs_tol=1e-10)):
            raise ValueError("ABBA_SUMMARY_MISMATCH")
    return True


def run(output, repeats, workers, max_seconds):
    if (type(repeats) is not int or not 15 <= repeats <= 30
        or not workers or len(workers) != len(set(workers))
        or any(w not in (1, 2, 4, 8) for w in workers)
        or not math.isfinite(max_seconds) or not 0 < max_seconds <= 1800):
        raise ValueError("ABBA_BUDGET")
    output = Path(output).resolve()
    started = time.monotonic()
    original_hashes = source_hashes()
    builds = {}
    executables = {}
    for name in VARIANTS:
        if time.monotonic() - started > max_seconds:
            raise RuntimeError("ABBA_TIME_BUDGET")
        exe, receipt = build_bio_workrooms(output.parent / "build" / name, ablation=name)
        builds[name] = receipt
        executables[name] = exe
    report = dict(protocol=PROTOCOL, status="RUNNING", variants=list(VARIANTS),
                  repeats=repeats, workers=list(workers),
                  head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  source_sha256=original_hashes,
                  environment=dict(system=platform.platform(), machine=platform.machine(),
                                   logical_cpus=os.cpu_count(),
                                   affinity=sorted(os.sched_getaffinity(0))
                                   if hasattr(os, "sched_getaffinity") else None),
                  builds=builds, cases=[],
                  limitations=[
                      "GitHub-hosted CPU, scheduling/frequency noise; results are descriptive",
                      "One process with three native warmups and one timed frame per build invocation",
                      "Fifteen sequential AB/BA matched rounds; not simultaneous randomized executions",
                      "Only two native fixture scenes; not a production PBR/GLB workload",
                      "Eight workers may oversubscribe GitHub's advertised CPU affinity",
                      "No hardware-GPU parity, perf-c2c HITM, power or thermal evidence",
                      "Exact framebuffer comparisons occur across real invocations, not independent Python rerender",
                      "No production renderer policy promotion from this report"])
    per_scene_digest = {}
    for name, pixels, tile, factory in CASES:
        scene = factory()
        ir = descriptor(pixels, pixels, tile)
        request_sha = digest(encode_request(ir, scene))
        for worker_count in workers:
            records = []
            for i in range(repeats):
                if time.monotonic() - started > max_seconds:
                    raise RuntimeError("ABBA_TIME_BUDGET")
                measured = {}
                cpu = {}
                for variant in order_for_pair(i):
                    result = run_bio_workrooms(executables[variant], ir, scene,
                                               worker_count, 1, "combined")
                    receipt = result["receipt"]
                    if receipt["handoff_ready"] is not True or receipt["worker_parity"] is not True:
                        raise RuntimeError("ABBA_NATIVE_PARITY")
                    if receipt["request_sha256"] != request_sha:
                        raise RuntimeError("ABBA_REQUEST_DRIFT")
                    image = digest(b"".join(result[k] for k in ("resolved", "rgba", "depth")))
                    if name in per_scene_digest and image != per_scene_digest[name]:
                        raise RuntimeError("ABBA_FRAME_MISMATCH")
                    per_scene_digest[name] = image
                    measured[variant] = receipt["samples_ms"][0]
                    cpu[variant] = receipt["cpu_samples_ms"][0]
                records.append(dict(pair=i, order=list(order_for_pair(i)),
                                    measured_ms=measured, cpu_ms=cpu))
            base = [p["measured_ms"]["default"] for p in records]
            static = [p["measured_ms"]["static-frontier-chunks"] for p in records]
            case = dict(scene=name, pixels=pixels, tile=tile,
                        triangles=len(scene), workers=worker_count,
                        request_sha256=request_sha,
                        image_depth_sha256=per_scene_digest[name],
                        pairs=records,
                        median_default_ms=statistics.median(base),
                        median_static_ms=statistics.median(static),
                        median_paired_delta_ms=statistics.median(s-d for d,s in zip(base,static)),
                        median_paired_static_over_default=statistics.median(s/d for d,s in zip(base,static)),
                        faster_static_pairs=sum(s < d for d,s in zip(base,static)))
            report["cases"].append(case)
            print(json.dumps({k:case[k] for k in ("scene", "workers", "median_default_ms",
                 "median_static_ms", "median_paired_delta_ms", "faster_static_pairs")}),flush=True)
    if source_hashes() != original_hashes:
        raise RuntimeError("ABBA_SOURCE_DRIFT")
    report["status"] = "PASS"
    report["seconds"] = time.monotonic() - started
    report["report_sha256"] = digest(canonical(report))
    verify_report(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output")
    p.add_argument("--verify")
    p.add_argument("--repeats",type=int,default=15)
    p.add_argument("--workers",type=int,nargs="+",default=[1,2,4,8])
    p.add_argument("--max-seconds",type=float,default=600)
    a=p.parse_args(argv)
    if a.verify:
        if a.output:
            p.error("--output and --verify are mutually exclusive")
        doc=json.loads(Path(a.verify).read_text(encoding="utf-8"))
        verify_report(doc)
        print("ABBA_REPORT_READBACK_OK",doc["report_sha256"])
    else:
        if not a.output:
            p.error("--output required")
        run(a.output,a.repeats,a.workers,a.max_seconds)


if __name__=="__main__":
    main()
