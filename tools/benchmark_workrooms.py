#!/usr/bin/env python3
"""Actual native render work, million-room scheduling, and framebuffer evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from software_gpu.research.workrooms import build_workrooms, descriptor, parse_descriptor, run_workrooms, to_framebuffer
from software_gpu.tests.test_workrooms import renderer_oracle, scene_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--repeats', type=int, default=15)
    args = parser.parse_args()
    if not 15 <= args.repeats <= 30:
        parser.error('15..30 repeats required')
    target = Path(args.output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    paths = ['native/symbolic/core.hpp', 'native/symbolic/workrooms.hpp', 'native/symbolic/workrooms_main.cpp',
             'software_gpu/research/workrooms.py', 'software_gpu/research/workrooms.wl',
             'software_gpu/tests/test_workrooms.py', 'software_gpu/tests/fixtures/workrooms-plan.json',
             'software_gpu/graphics/geometry.py', 'software_gpu/graphics/postprocess.py',
             'tools/benchmark_workrooms.py', 'native/symbolic/workrooms_wire.hpp']
    def hashes():
        return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    before = hashes()
    exe, build = build_workrooms(target/'native')
    scene = scene_fixture()
    # The descriptor really came from the checked-in Wolfram evaluator output.
    ir = parse_descriptor((ROOT/paths[6]).read_text(encoding='utf-8'))
    resolved, final = renderer_oracle(ir['width'], ir['height'], scene)
    small = run_workrooms(exe, ir, scene, workers=4)
    assert small['resolved'] == resolved.color_buffer.tobytes()
    assert small['rgba'] == final.color_buffer.tobytes()
    assert small['depth'] == final.depth_buffer.astype('<f4').tobytes()
    cases = []
    by_tile = {}
    # A one-pixel room proves scale; a 16x16 room measures a practical unit.
    # Independent process batches, no concurrent timing runs and no claim of
    # paired or hardware-GPU speedups.
    for tile, workers in [(1, 1), (1, 4), (16, 4), (16, 1)]:
        start = time.perf_counter_ns()
        out = run_workrooms(exe, descriptor(640, 640, tile), scene, workers, args.repeats)
        process_ms = (time.perf_counter_ns()-start)/1e6
        buffers = b''.join(out[k] for k in ('resolved', 'rgba', 'depth'))
        digest = hashlib.sha256(buffers).hexdigest()
        by_tile.setdefault(tile, digest)
        assert by_tile[tile] == digest
        assert digest == next(iter(by_tile.values()))
        r = out['receipt']
        case = dict(tile=tile, workers=workers, median_ms=statistics.median(r['samples_ms']),
                    median_cpu_ms=statistics.median(r['cpu_samples_ms']),
                    process_ms_including_startup_warmup_protocol_and_all_repeats=process_ms,
                    all_buffers_sha256=digest, native=r)
        cases.append(case)
        print(json.dumps({k: case[k] for k in ('tile', 'workers', 'median_ms', 'median_cpu_ms')}), flush=True)
        if tile == 16 and workers == 1:
            fb = to_framebuffer(out)
            # Exact image data, no labels confused with operation colours.
            (target/'render.ppm').write_bytes(b'P6\n640 640\n255\n'+fb.color_buffer[..., :3].tobytes())
    after = hashes()
    assert before == after
    ratios = {}
    for tile in (1, 16):
        group = {c['workers']: c['median_ms'] for c in cases if c['tile'] == tile}
        ratios[str(tile)] = group[1]/group[4]
    report = dict(protocol='are.workrooms.benchmark.v1', status='PASS',
        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        source_sha256=before, source_after_sha256=after, build=build, cases=cases,
        repeats=args.repeats, width=640, height=640, triangles=len(scene),
        oracle='existing MSAARasterizer + FXAAPass: 32x32 rgba, resolved rgba and depth exact',
        wolfram_descriptor_receipt=small['receipt'],
        four_worker_ratio_of_medians=ratios,
        environment=dict(platform=platform.platform(), python=platform.python_version(), machine=platform.machine()),
        limitations=['CPU software rendering only; final node returns CPU buffers, no GPU API submission',
          'Already-clipped finite geometry and flat per-triangle colour only; not a full shader/clipper port',
          'Four ordered global waves are a conservative dependency scheduler, not a physical wave equation',
          'Native repeats use resident input/output buffers; startup, parsing, copying and allocations excluded',
          'Every timed frame includes scheduling, worker creation/join and handoff readiness scan',
          'Native worker parity and tile parity are full-buffer checks; independent Python oracle runs at small size',
          'One host, independent process batches, descriptive speed ratios only',
          'No temperature sensors or thermal safety conclusion; C++ can fully load a CPU',
          'OpenProblems graph/method/metric structure is inspiration, no biological dataset or eigensolver port'])
    (target/'benchmark.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
