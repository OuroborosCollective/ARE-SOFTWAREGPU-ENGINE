#!/usr/bin/env python3
"""Bounded SoftwareGPU workbench. No provider, GPU or publication calls."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import sys

BENCHMARK_SOURCES = (
    "software_gpu/benchmarks/compare_surface_plans.py",
    "software_gpu/benchmarks/compare_tile_backends.py",
    "software_gpu/integrations/aurion/offline_render_worker.py",
    *("software_gpu/graphics/" + name for name in (
        "rasterizer.py", "geometry.py", "tile_backend.py", "surface_plan.py",
        "framebuffer.py", "batch_shader.py", "shader.py")))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def root_path(path):
    root = Path(path).resolve()
    require((root / "software_gpu/graphics/rasterizer.py").is_file() and
            (root / "Memory.md").is_file(), "SOFTWAREGPU_REPOSITORY_REQUIRED")
    return root


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout


def inspect(root):
    files = git(root, "ls-files", "-z").split("\0")
    areas = {name: [] for name in ("production", "test", "persistence", "effect", "core", "runtime-projection")}
    for name in filter(None, files):
        area = ("test" if "/tests/" in name or name.startswith("fixtures/") else
                "persistence" if name == "Memory.md" or name.startswith("evidence/") else
                "effect" if name.startswith((".github/", "scripts/")) else
                "core" if name.startswith(("software_gpu/graphics/", "software_gpu/core/")) else
                "production" if name.endswith(".py") else "runtime-projection")
        areas[area].append(name)
    return {"protocol": "are.softwaregpu-workbench-inspect.v1", "head": git(root, "rev-parse", "HEAD").strip(),
            "dirty": bool(git(root, "status", "--porcelain")), "areas": areas,
            "authority": "static-inventory-only", "runtime_activation_proven": False,
            "entrypoints": ["software_gpu.graphics.rasterizer.SoftwareRasterizer",
                            "software_gpu.benchmarks.compare_surface_plans",
                            "software_gpu.integrations.aurion.offline_render_worker",
                            "scripts/miha_cpu_runner.py"],
            "source_sha256": {str(p.relative_to(root)): digest(p) for p in
                              (root / "software_gpu/graphics").glob("*.py")}}


def audit(path, root=None):
    receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    require(receipt.get("protocol") == "are.surface-plan-benchmark.v1", "BENCHMARK_PROTOCOL_INVALID")
    results = receipt.get("results")
    require(isinstance(results, list) and results, "BENCHMARK_RESULTS_MISSING")
    provenance = "declared-artifact-only"
    if root is not None:
        sources = receipt.get("source_paths_sha256")
        require(isinstance(sources, dict) and bool(sources), "SOURCE_PATHS_REQUIRED_FOR_CHECKOUT_AUDIT")
        require(set(BENCHMARK_SOURCES) <= sources.keys(), "BENCHMARK_SOURCE_BINDING_INCOMPLETE")
        for name, expected in sources.items():
            target = (root / name).resolve()
            require(target.is_relative_to(root) and target.is_file(), "SOURCE_PATH_INVALID")
            require(digest(target) == expected, "CHECKOUT_SOURCE_MISMATCH:" + name)
        provenance = "all-declared-sources-match-checkout"
    rows = []
    for case in results:
        require(case.get("byte_identical") is True and case.get("gpu_parity_established") is False,
                "REPORTED_RENDER_CONTRACT_INVALID")
        require(bool(re.fullmatch(r"[0-9a-f]{64}", case.get("image_sha256", ""))), "IMAGE_DIGEST_INVALID")
        samples = case["samples_ms"]
        require("tiles" in samples, "TILES_BASELINE_MISSING")
        for label, values in samples.items():
            require(len(values) == case["repeats"] and all(type(v) in (int, float) and
                    math.isfinite(v) and v > 0 for v in values), "TIMING_SAMPLES_INVALID")
            median = statistics.median(values)
            require(math.isclose(median, case["median_frame_ms"][label], rel_tol=1e-10), "MEDIAN_MISMATCH")
            if "stats_ms" in case:
                s = case["stats_ms"][label]
                ordered = sorted(values)
                def percentile(q):
                    i = (len(ordered) - 1) * q
                    lower = int(i)
                    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (i - lower)
                expected = {"n": len(values), "median": median,
                            "iqr": percentile(.75) - percentile(.25),
                            "mad": statistics.median(abs(v - median) for v in values),
                            "min": min(values), "max": max(values)}
                require(all(k in s and math.isclose(s[k], v, rel_tol=1e-10, abs_tol=1e-10)
                            for k, v in expected.items()), "STATS_MISMATCH")
            if "speedup_paired" in case:
                ratios = [base / value for base, value in zip(samples["tiles"], values)]
                require(math.isclose(statistics.median(ratios), case["speedup_paired"][label]["median"],
                                     rel_tol=1e-10), "PAIRED_RATIO_MISMATCH")
        for p in case["plans"].values():
            require(p.get("protocol") == "are.surface-plan.v1", "PLAN_PROTOCOL_INVALID")
            body = {key: value for key, value in p.items() if key != "plan_sha256"}
            raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            require(hashlib.sha256(raw).hexdigest() == p["plan_sha256"], "PLAN_DIGEST_MISMATCH")
            c = p["counts"]
            if "binned_pairs" in p:
                require(type(p["binned_pairs"]) is int and type(p["small_pairs"]) is int
                        and 0 <= p["small_pairs"] <= p["binned_pairs"],
                        "PAIR_FEATURES_INVALID")
            if c is not None:
                require(all(type(v) is int and v >= 0 for v in c.values()), "COUNTER_INVALID")
                if "batch_fragment_samples" in c:
                    require(c["shaded_samples"] == c["batch_fragment_samples"] + c["scalar_fragment_calls"],
                            "SHADER_SAMPLE_PARTITION_INVALID")
                if "binned_pairs" in p:
                    require(p["binned_pairs"] == sum(c[k] for k in
                            ("inside", "outside", "boundary", "scan_bypassed")), "PAIR_PARTITION_INVALID")
                    require(p["small_pairs"] == c["scan_bypassed"], "SMALL_PAIR_PARTITION_INVALID")
        rows.append({"scene": case["scene"], "pixels": case["pixels"], "repeats": case["repeats"],
                     "modes": list(samples), "reported_byte_identical": True})
    return receipt, {"status": "PASS", "authority": "artifact-consistency-only",
                     "artifact_sha256": digest(path), "source_verification": provenance,
                     "independent_rerender_performed": False, "rows": rows}


def analyze(paths, root=None):
    cases = []
    for path in paths:
        receipt, verification = audit(path, root)
        for case in receipt["results"]:
            samples = case["samples_ms"]
            names = ("abl-noscan-scalar", "abl-noscan-batch", "abl-scan-scalar", "abl-scan-batch")
            require(all(n in samples for n in names), "FOUR_ABLATION_MODES_REQUIRED")
            def ratios(a, b):
                values = [x / y for x, y in zip(samples[a], samples[b])]
                median = statistics.median(values)
                return {"median": median, "mad": statistics.median(abs(v - median) for v in values)}
            cases.append({"scene": case["scene"], "pixels": case["pixels"], "repeats": case["repeats"],
                          "artifact_sha256": verification["artifact_sha256"],
                          "source_verification": verification["source_verification"],
                          "batch_gain_without_scan": ratios(names[0], names[1]),
                          "scan_gain_scalar": ratios(names[0], names[2]),
                          "scan_gain_batch": ratios(names[1], names[3]),
                          "noscan_batch_vs_tiles": ratios("tiles", names[1])})
    return {"status": "PASS", "cases": cases, "scope": "paired descriptive effects from supplied artifacts",
            "runtime_gate_calibrated": False, "coefficients_deployed": False,
            "next_step": "size/triangle sweeps and scene-family holdout before fitting any pre-execution gate"}


def execute(root, command, output, seconds):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    head = git(root, "rev-parse", "HEAD").strip()
    sources = {str(p.relative_to(root)): digest(p) for p in root.rglob("*.py") if ".git" not in p.parts}
    try:
        result = subprocess.run(command, cwd=root, timeout=seconds, capture_output=True, text=True)
    except subprocess.TimeoutExpired as exc:
        report = {"status": "TIMEOUT", "head": head, "seconds": seconds}
        (output / "workbench-run.json").write_text(json.dumps(report, indent=2) + "\n")
        raise ValueError("WORKBENCH_PROCESS_BUDGET_EXCEEDED") from exc
    (output / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (output / "stderr.log").write_text(result.stderr, encoding="utf-8")
    report = {"status": "PASS" if result.returncode == 0 else "FAIL", "head": head,
              "head_after": git(root, "rev-parse", "HEAD").strip(), "returncode": result.returncode,
              "command": command, "source_sha256": sources, "stdout_sha256": digest(output / "stdout.log"),
              "stderr_sha256": digest(output / "stderr.log"), "scope": "actual command exit and logs"}
    report["source_after_sha256"] = {str(p.relative_to(root)): digest(p) for p in root.rglob("*.py")
                                     if ".git" not in p.parts}
    (output / "workbench-run.json").write_text(json.dumps(report, indent=2) + "\n")
    require(result.returncode == 0, "WORKBENCH_REAL_COMMAND_FAILED:" + str(result.returncode))
    require(report["head"] == report["head_after"] and sources == report["source_after_sha256"],
            "WORKBENCH_SOURCE_CHANGED_DURING_RUN")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "verify", "benchmark", "train-preflight"):
        p = sub.add_parser(action)
        p.add_argument("--root", required=True)
        p.add_argument("--output", required=True)
        if action != "inspect":
            p.add_argument("--seconds", type=float, default=1800)
        if action == "benchmark":
            p.add_argument("--pixels", type=int, default=256)
            p.add_argument("--repeats", type=int, default=15)
            p.add_argument("--workers", type=int, default=1)
            p.add_argument("--ablation", action="store_true")
    p = sub.add_parser("audit")
    p.add_argument("artifact")
    p.add_argument("--output", required=True)
    p.add_argument("--root", help="require all declared source hashes to match this checkout")
    p = sub.add_parser("analyze")
    p.add_argument("artifacts", nargs="+")
    p.add_argument("--output", required=True)
    p.add_argument("--root", help="require all declared source hashes to match this checkout")
    args = parser.parse_args(argv)
    if args.action in ("audit", "analyze"):
        root = root_path(args.root) if args.root else None
        result = audit(args.artifact, root)[1] if args.action == "audit" else analyze(args.artifacts, root)
        target = Path(args.output).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else:
        root = root_path(args.root)
        if args.action == "inspect":
            result = inspect(root)
            target = Path(args.output).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        else:
            require(math.isfinite(args.seconds) and args.seconds > 0, "FINITE_POSITIVE_BUDGET_REQUIRED")
            if args.action == "verify":
                command = [sys.executable, "-m", "unittest", "discover", "-s", "software_gpu/tests", "-v"]
            elif args.action == "train-preflight":
                command = [sys.executable, "scripts/miha_cpu_runner.py", "preflight", "--output", str(Path(args.output).resolve())]
            else:
                command = [sys.executable, "-m", "software_gpu.benchmarks.compare_surface_plans",
                           "--output-dir", str(Path(args.output).resolve()), "--pixels", str(args.pixels),
                           "--repeats", str(args.repeats), "--workers", str(args.workers),
                           "--max-seconds", str(args.seconds)]
                if args.ablation:
                    command.append("--ablation")
            # The renderer itself bounds benchmark children; let its supervisor
            # reap them before this outer guard fires.
            result = execute(root, command, args.output, args.seconds + 10)
            if args.action == "benchmark":
                audit(Path(args.output) / "surface-plan-benchmark.json", root)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print("SOFTWAREGPU_WORKBENCH_FAIL:" + str(exc), file=sys.stderr)
        raise SystemExit(1)
