#!/usr/bin/env python3
"""Fail-closed, non-root benchmark launcher for a shared Sovereign/Aurion VPS.

No services, sockets, containers or permissions are modified. Python orchestrates
the existing *real* native C++17 benchmark and hashes its readback.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3
PROFILES = {
    "pilot": {"workers": [1, 2], "variants": ["default", "padded-pending"],
              "free_gib": 8, "memory_gib": 4, "max_disk_used": .85,
              "max_load_per_cpu": .60, "min_cpus": 2, "limit_cpus": 2,
              "budget_seconds": 300, "wall_seconds": 420},
    "full": {"workers": [1, 2, 4, 8],
             "variants": ["default", "padded-pending", "release-fence", "padded-release-fence"],
             "free_gib": 20, "memory_gib": 8, "max_disk_used": .85,
             "max_load_per_cpu": .15, "min_cpus": 8, "limit_cpus": 8,
             "budget_seconds": 1200, "wall_seconds": 1380},
}


class HostGateError(RuntimeError):
    pass


def _mem_available_bytes():
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise HostGateError("MEMAVAILABLE_UNAVAILABLE")


def snapshot(path: Path = ROOT):
    if sys.platform != "linux":
        raise HostGateError("LINUX_REQUIRED")
    affinity = sorted(os.sched_getaffinity(0))
    total, used, free = shutil.disk_usage(path)
    if not affinity or total <= 0:
        raise HostGateError("HOST_CPU_OR_DISK_UNAVAILABLE")
    return {"logical_cpus": os.cpu_count(), "affinity": affinity,
            "load_1m": os.getloadavg()[0], "load_5m": os.getloadavg()[1],
            "mem_available_bytes": _mem_available_bytes(),
            "disk_total_bytes": total, "disk_free_bytes": free,
            "disk_used_fraction": used / total}


def admission(metrics, profile):
    """Pure decision: production protection wins over speed, independent of CI."""
    if profile not in PROFILES:
        raise ValueError("PROFILE_UNKNOWN")
    p = PROFILES[profile]
    failures = []
    cpus = len(metrics["affinity"])
    if cpus < p["min_cpus"]:
        failures.append("CPU_AFFINITY_INSUFFICIENT")
    if metrics["mem_available_bytes"] < p["memory_gib"] * GIB:
        failures.append("MEMORY_HEADROOM_LOW")
    if metrics["disk_free_bytes"] < p["free_gib"] * GIB:
        failures.append("DISK_FREE_LOW")
    if metrics["disk_used_fraction"] >= p["max_disk_used"]:
        failures.append("DISK_PRESSURE_HIGH")
    load_ratio = metrics["load_1m"] / max(1, cpus)
    if load_ratio > p["max_load_per_cpu"]:
        failures.append("CPU_LOAD_NOT_QUIET")
    return {"profile": profile, "status": "GO" if not failures else "STOP",
            "failures": failures, "load_per_affinity_cpu": round(load_ratio, 4),
            "available_cpus": cpus, "selected_cpus": metrics["affinity"][:p["limit_cpus"]],
            "limits": {"nice": 15, "address_space_gib": 4,
                       "file_size_gib": 1, "cpu_seconds": 900,
                       "wall_seconds": p["wall_seconds"],
                       "no_listening_ports": True}}


def verified_head(expected_sha: str):
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise HostGateError("EXPECTED_SHA_REQUIRED")
    got = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if got != expected_sha:
        raise HostGateError("SOURCE_SHA_MISMATCH")
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
                                    cwd=ROOT, text=True).strip()
    if dirty:
        raise HostGateError("TRACKED_SOURCE_DIRTY")
    return got


def _child_limits(cpus):
    os.nice(15)
    os.sched_setaffinity(0, set(cpus))
    resource.setrlimit(resource.RLIMIT_AS, (4 * GIB, 4 * GIB))
    resource.setrlimit(resource.RLIMIT_FSIZE, (GIB, GIB))
    resource.setrlimit(resource.RLIMIT_CPU, (900, 900))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _run_bounded(cmd, cpus, seconds):
    proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True,
                            preexec_fn=lambda: _child_limits(cpus))
    try:
        out, _ = proc.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
        raise HostGateError("WALL_BUDGET_EXCEEDED")
    if proc.returncode != 0:
        raise HostGateError("BENCHMARK_EXIT_" + str(proc.returncode) +
                            ": " + out[-1600:])
    return out


def run(args):
    if os.geteuid() == 0:
        raise HostGateError("NONROOT_ONLY")
    head = verified_head(args.expected_sha)
    metrics = snapshot(ROOT)
    gate = admission(metrics, args.profile)
    print(json.dumps({"source_sha": head, "host": metrics, "admission": gate},
                     sort_keys=True), flush=True)
    if args.action == "inspect":
        return 0 if gate["status"] == "GO" else 2
    if gate["status"] != "GO":
        raise HostGateError("VPS_RESOURCE_GATE_CLOSED:" + ",".join(gate["failures"]))
    if args.profile == "full" and not args.confirm_full_window:
        raise HostGateError("FULL_WINDOW_REQUIRES_CONFIRMATION")
    if not args.output_base.is_absolute():
        raise HostGateError("OUTPUT_BASE_ABSOLUTE_REQUIRED")
    base = args.output_base.resolve()
    # A plan is a read-only proposal; it must not create directories or lock files.
    if args.action == "plan":
        p = PROFILES[args.profile]
        cmd = [sys.executable, str(ROOT / "tools/benchmark_frontier_cache.py"),
               "--output-dir", str(base / ("<UTCSTAMP>-" + head[:12] + "-" + args.profile)),
               "--repeats", "15", "--max-seconds", str(p["budget_seconds"]),
               "--workers", *map(str, p["workers"]), "--variants", *p["variants"]]
        print(json.dumps({"planned_command": cmd, "output_base": str(base),
                          "executed": False, "writes": False}), flush=True)
        return 0
    # Existing shared-host disk must be below the stricter sovereign P0 threshold.
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_disk = snapshot(base)
    output_gate = admission(output_disk, args.profile)
    if output_gate["status"] != "GO":
        raise HostGateError("OUTPUT_FS_GATE_CLOSED:" + ",".join(output_gate["failures"]))
    with (base / ".single-run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HostGateError("CONCURRENT_BENCHMARK_FORBIDDEN") from None
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = base / (stamp + "-" + head[:12] + "-" + args.profile)
        dest.mkdir(mode=0o700)
        p = PROFILES[args.profile]
        cmd = [sys.executable, str(ROOT / "tools/benchmark_frontier_cache.py"),
               "--output-dir", str(dest), "--repeats", "15",
               "--max-seconds", str(p["budget_seconds"]), "--workers",
               *map(str, p["workers"]), "--variants", *p["variants"]]
        log = _run_bounded(cmd, gate["selected_cpus"], p["wall_seconds"])
        (dest / "native-output.log").write_text(log, encoding="utf-8")
        receipt = dest / "benchmark.json"
        if not receipt.is_file():
            raise HostGateError("BENCHMARK_RECEIPT_MISSING")
        data = json.loads(receipt.read_text(encoding="utf-8"))
        expected_cases = 2 * len(p["workers"]) * len(p["variants"])
        if (data.get("status") != "PASS" or data.get("head") != head or
                len(data.get("cases", [])) != expected_cases or
                not all(z.get("full_frame_parity") for z in data["cases"])):
            raise HostGateError("BENCHMARK_READBACK_FAILED")
        summary = {"protocol": "are.bio-host-readback.v1", "status": "PASS",
                   "source_sha": head, "profile": args.profile,
                   "host": metrics, "admission": gate, "cases": expected_cases,
                   "benchmark_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                   "output_dir": str(dest),
                   "limitations": ["Shared VPS with Sovereign/Aurion; host noise affects timings",
                                   "perf c2c availability not verified",
                                   "CPU-vs-CPU only; no GPU parity"]}
        (dest / "vps-host-readback.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, sort_keys=True), flush=True)
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("inspect", "plan", "run"))
    ap.add_argument("--profile", choices=tuple(PROFILES), default="pilot")
    ap.add_argument("--expected-sha", required=True)
    ap.add_argument("--output-base", type=Path, default=Path.home() /
                    ".local/share/are-softwaregpu/results")
    ap.add_argument("--confirm-full-window", action="store_true")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except (HostGateError, OSError, subprocess.SubprocessError) as exc:
        print("HOST_GATE_STOP: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
