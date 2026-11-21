"""Issue #293: offline measured GLB2 resource comparison (NOT a full-frame or exporter benchmark).

The historical control implementation and deterministic fixtures are test/benchmark-only.
No external/private asset or native importer admission is implied.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc

from software_gpu.tests.fixtures.glb_resource_fixture import make_resource_glb
from tools.glb_container_preflight import inspect_glb

PROTOCOL = "are.glb-resource-microbenchmark.v1"
REPEATS = 15
MESH_COUNTS = (1, 100, 1300, 3500)


def historical_copy_control(data: bytes) -> dict:
    """Pinned benchmark-only historical GLB2 parser, never registered as an importer."""
    import struct
    if len(data) < 20 or data[:4] != b'glTF':
        raise ValueError('invalid GLB header')
    version, total = struct.unpack_from('<II', data, 4)
    if version != 2 or total != len(data):
        raise ValueError('GLB version/length mismatch')
    pos, chunks = 12, []
    while pos < total:
        if total - pos < 8:
            raise ValueError('truncated chunk header')
        size, kind = struct.unpack_from('<II', data, pos)
        pos += 8
        if size % 4 or size > total - pos:
            raise ValueError('invalid chunk size')
        chunks.append((kind, data[pos:pos + size]))
        pos += size
    if not chunks or chunks[0][0] != 0x4E4F534A:
        raise ValueError('first chunk must be JSON')
    if len(chunks) > 2 or (len(chunks) == 2 and chunks[1][0] != 0x004E4942):
        raise ValueError('unexpected GLB chunk layout')
    try:
        doc = json.loads(chunks[0][1].decode('utf-8').rstrip(' '))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('invalid JSON chunk') from exc
    if not isinstance(doc, dict) or not isinstance(doc.get('asset'), dict) or doc['asset'].get('version') != '2.0':
        raise ValueError('not a glTF 2.0 asset')
    for name in ('meshes', 'animations', 'buffers'):
        if not isinstance(doc.get(name, []), list):
            raise ValueError(f'{name} must be an array')
    for mesh in doc.get('meshes', []):
        if not isinstance(mesh, dict) or not isinstance(mesh.get('primitives', []), list):
            raise ValueError('invalid mesh primitives')
        for primitive in mesh.get('primitives', []):
            if not isinstance(primitive, dict) or not isinstance(primitive.get('targets', []), list):
                raise ValueError('invalid primitive targets')
    buffers = doc.get('buffers', [])
    if len(buffers) > 1 or (buffers and not isinstance(buffers[0], dict)):
        raise ValueError('unsupported embedded buffer layout')
    if len(chunks) == 2 and (not buffers or 'uri' in buffers[0]):
        raise ValueError('unreferenced BIN chunk')
    if buffers and 'uri' not in buffers[0]:
        if len(chunks) != 2:
            raise ValueError('missing BIN chunk')
        declared = buffers[0].get('byteLength')
        if type(declared) is not int or declared < 0 or not (declared <= len(chunks[1][1]) <= declared + 3):
            raise ValueError('BIN length mismatch')
    return {'meshes': len(doc.get('meshes', [])), 'animations': len(doc.get('animations', [])),
            'morph_targets': sum(len(p.get('targets', [])) for m in doc.get('meshes', [])
                                 for p in m.get('primitives', [])), 'bytes': len(data)}


def summary(values):
    values = sorted(values)
    median = statistics.median(values)
    percentile = lambda t: values[int(t)] + (values[min(int(t) + 1, len(values) - 1)] - values[int(t)]) * (t - int(t))
    return {'n': len(values), 'median': median, 'p95': percentile((len(values)-1)*.95),
            'iqr': percentile((len(values)-1)*.75)-percentile((len(values)-1)*.25),
            'mad': statistics.median(abs(v-median) for v in values),
            'min': values[0], 'max': values[-1]}


def measure_one(raw: bytes):
    times = {'historical_copy': [], 'zero_copy_view': []}
    alloc = {'historical_copy': [], 'zero_copy_view': []}
    functions = {'historical_copy': historical_copy_control, 'zero_copy_view': inspect_glb}
    expected = historical_copy_control(raw)
    assert inspect_glb(raw) == expected
    for iteration in range(REPEATS + 1):
        for mode in (('historical_copy', 'zero_copy_view') if iteration % 2 == 0
                     else ('zero_copy_view', 'historical_copy')):
            gc.collect()
            tracemalloc.start()
            tracemalloc.reset_peak()
            before = tracemalloc.get_traced_memory()[0]
            start = time.perf_counter_ns()
            actual = functions[mode](raw)
            elapsed = (time.perf_counter_ns() - start) / 1e6
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            if actual != expected:
                raise AssertionError('GLB_RESOURCE_OUTCOME_PARITY')
            if iteration:
                times[mode].append(elapsed)
                alloc[mode].append(max(0, peak - before))
    paired = [old/new for old,new in zip(times['historical_copy'], times['zero_copy_view'])]
    return {'samples_ms': times, 'peak_traced_allocation_bytes': alloc,
            'statistics_ms': {name: summary(values) for name, values in times.items()},
            'statistics_alloc_bytes': {name: summary(values) for name, values in alloc.items()},
            'paired_speed_ratio': summary(paired), 'byte_identical_input': True,
            'semantic_results_identical': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bin-bytes', type=int, default=4 << 20)
    args = parser.parse_args(argv)
    if args.bin_bytes < 44 or args.bin_bytes > (16 << 20) or args.bin_bytes % 4:
        parser.error('bin-bytes 44..16777216 divisible by four')
    from tools import glb_container_preflight
    from software_gpu.tests.fixtures import glb_resource_fixture
    root = Path(__file__).resolve().parents[2]
    paths = [Path(__file__).resolve(), Path(glb_container_preflight.__file__).resolve(),
             Path(glb_resource_fixture.__file__).resolve()]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    rows = []
    for meshes in MESH_COUNTS:
        raw = make_resource_glb(meshes, bin_bytes=args.bin_bytes)
        rows.append({'mesh_count': meshes, 'input_bytes': len(raw),
                     'asset_sha256': hashlib.sha256(raw).hexdigest(),
                     'asset_class': 'generated_valid_glb2_fixture_not_independent_asset',
                     'results': measure_one(raw)})
    report = {
        'protocol': PROTOCOL, 'repeats': REPEATS, 'source_revision': revision,
        'bench_scope': 'container_preflight_only',
        'native_multi_mesh_import_supported': False, 'export_benchmarked': False,
        'full_frame_benchmarked': False, 'automatic_activation': False,
        'cpu': platform.processor() or platform.machine(), 'os': platform.platform(),
        'python': platform.python_version(),
        'affinity_cpus': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
        'source_paths_sha256': {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        'rows': rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n')
    print('GLB_RESOURCE_MICROBENCHMARK_OK', [x['mesh_count'] for x in rows])


if __name__ == '__main__':
    main()