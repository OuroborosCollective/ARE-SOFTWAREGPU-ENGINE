#!/usr/bin/env python3
"""Coverage gate for the SoftwareGPU CPU suite (stdlib only, Python >= 3.12).

Runs the full unittest suite under sys.monitoring line events, measures line
coverage of the package code (tests themselves are excluded), and fails with
exit code 1 if any floor is violated.

Why this exists: CI must turn red when the rendering core loses test coverage,
not just when a test fails. Floors are minimums; the JIT lane (numba installed)
covers software_gpu/graphics/compiled_tile.py additionally, so that file
carries no floor here.

Deliberately excluded from per-file floors (still counted in the overall
number): demos, benchmarks and example scripts. They run as CI steps but are
not unit-test targets. software_gpu/integrations/aurion/_offline_child.py
executes in the isolation subprocess by design; its behaviour is asserted via
worker receipts, so it carries no floor either.

Usage: python tools/coverage_gate.py [--verbose]
Environment: set COVERAGE_GATE_INNER=1 internally (prevents recursion when the
suite itself contains the gate test).
"""
from __future__ import annotations

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

PKG_PREFIX = os.path.join(REPO_ROOT, "software_gpu") + os.sep
MAIN_PY = os.path.join(REPO_ROOT, "main.py")

# Per-file floors in percent, measured on the CPU lane (no numba) after the
# gap-closure slice, minus a 2 point margin. Raise only deliberately.
FLOORS = {
    "software_gpu/graphics/framebuffer.py": 95.0,
    "software_gpu/graphics/geometry.py": 94.0,
    "software_gpu/graphics/rasterizer.py": 98.0,
    "software_gpu/graphics/tile_backend.py": 88.0,
    "software_gpu/graphics/shader.py": 88.0,
    "software_gpu/graphics/postprocess.py": 95.0,
    "software_gpu/network/security.py": 88.0,
    "software_gpu/integrations/aurion/offline_render_worker.py": 78.0,
    "main.py": 35.0,
}
OVERALL_FLOOR = 63.0  # percent of all package lines (incl. demos/benchmarks)


def collect_hits():
    """Run the suite under line monitoring; return {filename: set(lines)}."""
    hits = {}

    def on_line(code, line):
        filename = code.co_filename
        if (filename.startswith(PKG_PREFIX) or filename == MAIN_PY):
            bucket = hits.get(filename)
            if bucket is None:
                bucket = set()
                hits[filename] = bucket
            bucket.add(line)
        return None

    monitor = sys.monitoring
    monitor.use_tool_id(monitor.COVERAGE_ID, "coverage-gate")
    monitor.register_callback(monitor.COVERAGE_ID, monitor.events.LINE, on_line)
    monitor.set_events(monitor.COVERAGE_ID, monitor.events.LINE)
    try:
        suite = unittest.TestLoader().discover(os.path.join(REPO_ROOT, "software_gpu", "tests"))
        result = unittest.TextTestRunner(verbosity=0).run(suite)
    finally:
        monitor.set_events(monitor.COVERAGE_ID, 0)
        monitor.free_tool_id(monitor.COVERAGE_ID)
    return hits, result


def executable_lines(path):
    with open(path, "rb") as handle:
        source = handle.read()
    lines = set()

    def walk(code):
        for _start, _end, line in code.co_lines():
            if line is not None and line > 0:
                lines.add(line)
        for const in code.co_consts:
            if hasattr(const, "co_lines"):
                walk(const)

    walk(compile(source, path, "exec"))
    return lines


def evaluate(per_file, overall):
    """Compare measured coverage against floors; return list of failures."""
    failures = []
    for rel, floor in FLOORS.items():
        actual = per_file.get(rel)
        if actual is None:
            failures.append(f"{rel}: file missing from measurement")
        elif actual < floor:
            failures.append(f"{rel}: {actual:.1f}% < floor {floor:.1f}%")
    if overall < OVERALL_FLOOR:
        failures.append(f"OVERALL: {overall:.1f}% < floor {OVERALL_FLOOR:.1f}%")
    return failures


def main(argv=None):
    verbose = "--verbose" in (argv or sys.argv[1:])
    if sys.version_info < (3, 12):
        print("COVERAGE_GATE_SKIP python<3.12 has no sys.monitoring")
        return 0

    env = dict(os.environ)
    env["COVERAGE_GATE_INNER"] = "1"
    os.environ["COVERAGE_GATE_INNER"] = "1"  # gate test inside suite skips itself

    hits, result = collect_hits()
    if not result.wasSuccessful():
        print(f"COVERAGE_GATE_FAIL suite itself failed "
              f"(failures={len(result.failures)} errors={len(result.errors)})")
        return 1

    files = []
    for root, _dirs, names in os.walk(os.path.join(REPO_ROOT, "software_gpu")):
        if f"{os.sep}tests" in root or "__pycache__" in root:
            continue
        for name in names:
            if name.endswith(".py"):
                files.append(os.path.join(root, name))
    files.append(MAIN_PY)

    total_exec = total_hit = 0
    per_file = {}
    for path in sorted(files):
        executable = executable_lines(path)
        covered = hits.get(path, set()) & executable
        total_exec += len(executable)
        total_hit += len(covered)
        rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
        per_file[rel] = (100.0 * len(covered) / len(executable)) if executable else 100.0

    overall = 100.0 * total_hit / total_exec if total_exec else 100.0
    failures = evaluate(per_file, overall)

    if verbose or failures:
        print("=== COVERAGE GATE REPORT (package code, tests excluded) ===")
        for rel in sorted(per_file):
            floor = FLOORS.get(rel)
            mark = f" (floor {floor:.0f}%)" if floor else ""
            print(f"  {per_file[rel]:6.1f}%  {rel}{mark}")
        print(f"  OVERALL {overall:.1f}% (floor {OVERALL_FLOOR:.0f}%), "
              f"{total_hit}/{total_exec} lines, tests run={result.testsRun}")
    if failures:
        for failure in failures:
            print("COVERAGE_GATE_FAIL " + failure)
        return 1
    print(f"COVERAGE_GATE_OK overall={overall:.1f}% floors={len(FLOORS)} "
          f"tests={result.testsRun}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
