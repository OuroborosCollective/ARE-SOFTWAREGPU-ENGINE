#!/usr/bin/env python3
"""Opt-in native ARE C++17 PBR benchmark for SHA-pinned owner GLB variants.

The benchmark never fetches assets or uploads frames. It requires a clean
checkout of ARE-SOFTWAREGPU-ENGINE, independently SHA-checked local model
files, and at least 15 real native samples per variant and worker setup.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time

import numpy as np

from tools.owner_lod_native_normals import inspect_lod


class OwnerBenchmarkError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise OwnerBenchmarkError(code)


def validate_manifest(data):
    require(isinstance(data, dict) and data.get('protocol') == 'are.owner-lod-native-benchmark.v1'
            and set(data) == {'protocol', 'models'} and isinstance(data['models'], list)
            and len(data['models']) == 2, 'OWNER_BENCH_MANIFEST')
    expected = {'forest-lord', 'emerald-grass'}
    seen = set()
    for model in data['models']:
        require(isinstance(model, dict) and set(model) == {'name', 'variants'}
                and model['name'] in expected and model['name'] not in seen,
                'OWNER_BENCH_MODEL')
        seen.add(model['name'])
        require(isinstance(model['variants'], list)
                and [v.get('label') for v in model['variants'] if isinstance(v, dict)]
                == ['original', 'lod0', 'lod1', 'lod2']
                and len(model['variants']) == 4, 'OWNER_BENCH_VARIANTS')
        for variant in model['variants']:
            require(isinstance(variant, dict)
                    and set(variant) == {'label', 'file', 'sha256', 'triangles'}
                    and isinstance(variant['file'], str)
                    and bool(re.fullmatch(r'[A-Za-z0-9 ._-]+\.glb', variant['file']))
                    and type(variant['sha256']) is str
                    and bool(re.fullmatch(r'[a-f0-9]{64}', variant['sha256']))
                    and type(variant['triangles']) is int
                    and 1 <= variant['triangles'] <= 8_000_000,
                    'OWNER_BENCH_VARIANT')
    require(seen == expected, 'OWNER_BENCH_REQUIRED_MODELS')
    return data['models']


def load_manifest(path):
    return validate_manifest(json.loads(Path(path).read_text(encoding='utf-8')))


def stats(values):
    require(isinstance(values, list) and 3 <= len(values) <= 30
            and all(type(v) in (float, int) and np.isfinite(v) and v >= 0 for v in values),
            'OWNER_BENCH_SAMPLES')
    sorted_values = sorted(values)
    mid = statistics.median(sorted_values)
    return dict(n=len(values), raw_ms=values, median_ms=mid,
                iqr_ms=float(np.percentile(values, 75) - np.percentile(values, 25)),
                mad_ms=statistics.median(abs(v - mid) for v in values),
                minimum_ms=min(values), maximum_ms=max(values))


def read_asset(path, expected_hash, expected_triangles):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 256 * 1024 * 1024,
            'OWNER_BENCH_FILE')
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected_hash, 'OWNER_BENCH_SHA')
    meta = inspect_lod(data, pbr=True)
    require(meta['triangles'] == expected_triangles, 'OWNER_BENCH_TRIANGLES')
    return {'file': path.name, 'sha256': expected_hash, 'bytes': len(data),
            'triangles': meta['triangles'], 'vertices': meta['vertices']}


def git_identity():
    root = Path(__file__).resolve().parents[1]
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True,
                                       stderr=subprocess.DEVNULL, timeout=8).strip()
    try:
        sha = git('rev-parse', 'HEAD')
        require(bool(re.fullmatch('[0-9a-f]{40}', sha)), 'OWNER_BENCH_GIT_SHA')
        require(not git('status', '--porcelain'), 'OWNER_BENCH_DIRTY_TREE')
        return sha
    except (subprocess.SubprocessError, OSError):
        raise OwnerBenchmarkError('OWNER_BENCH_GIT_READBACK') from None


def environment():
    return dict(python=sys.version.split()[0], numpy=np.__version__,
                os=platform.platform(), cpu=platform.processor(),
                affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
                processors=os.cpu_count())


def run_native(models, asset_dir, output_dir, seconds=1800, repeats=15, pixels=128):
    from software_gpu.research.model_probe import build_model_probe, load_asset, write_scene, run_model
    require(30 <= seconds <= 1800 and 15 <= repeats <= 30 and pixels in (64, 128, 256),
            'OWNER_BENCH_BOUNDS')
    sha = git_identity()
    start = time.monotonic()
    out = Path(output_dir)
    require(not out.exists(), 'OWNER_BENCH_OUTPUT_EXISTS')
    out.mkdir(parents=True)
    executable, build = build_model_probe(out / 'native-build')
    result = dict(protocol='are.owner-lod-native-render.v1', status='INCOMPLETE',
                  git_sha=sha, native_build=build, env=environment(),
                  repeats=repeats, pixels=pixels, seconds_budget=seconds,
                  projection='perspective', render_profile='pbr',
                  paired_claim=False, models=[], hardware_gpu_submitted=False)
    for model in models:
        rows = []
        for variant in model['variants']:
            elapsed = time.monotonic() - start
            require(elapsed < seconds - 40, 'OWNER_BENCH_TIME_BUDGET')
            path = Path(asset_dir) / variant['file']
            identity = read_asset(path, variant['sha256'], variant['triangles'])
            asset = load_asset(path, {'bytes': identity['bytes'], 'sha256': identity['sha256']}, profile='pbr')
            request = out / f"{model['name']}-{variant['label']}.aremdl"
            entry = write_scene(request, [dict(asset=asset, clip=None)], [0.0] * repeats,
                                pixels=pixels, tile=32, projection='perspective', render_profile='pbr')
            measurements = []
            for workers in (1, 4):
                remaining = seconds - (time.monotonic() - start)
                require(remaining > 30, 'OWNER_BENCH_TIME_BUDGET')
                frame = run_model(executable, request, workers=workers, repeats=repeats,
                                  render_profile='pbr', mode='render', timeout=min(600, int(remaining)))
                receipt = frame['receipt']
                require(receipt.get('hardware_gpu_submitted') is False
                        and receipt.get('full_buffer_parity') is True
                        and sum(receipt['sample_writes']) > 0,
                        'OWNER_BENCH_NATIVE_FRAME')
                measurements.append((frame, dict(workers=workers,
                      candidate=stats(receipt['candidate_total_ms']),
                      baseline=stats(receipt['baseline_total_ms']),
                      frame_sha256=receipt['frame_sha256'],
                      resolved_sha256=hashlib.sha256(frame['resolved'].tobytes()).hexdigest(),
                      depth_sha256=hashlib.sha256(frame['depth'].tobytes()).hexdigest(),
                      runtime_receipt=receipt)))
            first, second = measurements
            for key in ('frames', 'resolved', 'depth'):
                require(np.array_equal(first[0][key], second[0][key]),
                        f'OWNER_BENCH_WORKER_{key.upper()}_DRIFT')
            rows.append(dict(label=variant['label'], source=identity,
                             input_sha256=entry['sha256'], profiles=[first[1], second[1]],
                             full_buffer_worker_parity=True))
            print('OWNER_BENCH_NATIVE_OK', model['name'], variant['label'],
                  first[1]['candidate']['median_ms'], second[1]['candidate']['median_ms'], flush=True)
        # All frames share the same camera and resolution. This is a descriptive,
        # sequential test, not an interleaved or paired statistical trial.
        base = next(x for x in rows if x['label'] == 'original')['profiles'][1]['candidate']['median_ms']
        result['models'].append(dict(name=model['name'], variants=rows,
             speedup_vs_original_4workers={r['label']: (base / r['profiles'][1]['candidate']['median_ms']
                 if r['profiles'][1]['candidate']['median_ms'] > 0 else None) for r in rows},
             evidence_limit='Sequential samples; geometry and quality differ; no FPS guarantee'))
    result['elapsed_seconds'] = time.monotonic() - start
    result['status'] = 'PASS'
    (out / 'native-owner-lod-evidence.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print('OWNER_BENCH_NATIVE_RECEIPT_OK', sha)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=int, default=1800)
    p.add_argument('--repeats', type=int, default=15)
    p.add_argument('--pixels', type=int, choices=[64,128,256], default=128)
    args = p.parse_args(argv)
    try:
        run_native(load_manifest(args.manifest), args.assets, args.output,
                   args.seconds, args.repeats, args.pixels)
        return 0
    except (OwnerBenchmarkError, ValueError, OSError, TimeoutError) as exc:
        print(f'OWNER_BENCH_BLOCKED:{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
