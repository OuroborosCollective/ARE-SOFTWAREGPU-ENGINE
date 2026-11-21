"""Offline stage-cost evidence for one admitted GLB2 asset. No runtime policy changes.

The stage calls are deliberately *independent*, not an additive pipeline total:
read_glb/load_asset perform their own read and parsing. Benchmarks are for
attribution, not full-frame FPS or multi-mesh import admission.
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
import tempfile
import time
import tracemalloc

import numpy as np

from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex
from software_gpu.research.model_probe import accessor, load_asset, read_glb
from software_gpu.tests.fixtures.glb_resource_fixture import make_resource_glb
from tools.glb_container_preflight import inspect_glb


def stat(values):
    ordered = sorted(values)
    def quantile(q):
        p = (len(ordered) - 1) * q
        i = int(p)
        return ordered[i] + (ordered[min(i+1, len(ordered)-1)] - ordered[i]) * (p-i)
    med = statistics.median(values)
    return dict(n=len(values), median=med, p95=quantile(.95), iqr=quantile(.75)-quantile(.25),
                mad=statistics.median(abs(x-med) for x in values), min=min(values), max=max(values))


def rss_status():
    """Linux current/peak RSS; cumulative process peak is NOT stage-attributed."""
    target = Path('/proc/self/status')
    if not target.exists():
        return None
    lines = target.read_text().splitlines()
    parts = {}
    for line in lines:
        if line.startswith(('VmRSS:', 'VmHWM:')):
            name, val = line.split(':', 1)
            try:
                parts[name + '_bytes'] = int(val.split()[0]) * 1024
            except (ValueError, IndexError):
                return None
    return parts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=15)
    args = parser.parse_args(argv)
    if args.repeats < 15 or args.repeats > 30:
        parser.error('15..30 stage repeats required')
    raw = make_resource_glb(1, bin_bytes=4096)
    digest = hashlib.sha256(raw).hexdigest()
    times = {name: [] for name in ('file_sha_read', 'preflight_json_bin', 'read_glb_io_json',
                                   'typed_accessor_decode', 'typed_import', 'first_draw',
                                   'followup_draw', 'release_gc')}
    traced_peaks = {key: [] for key in times}
    rgba, depths = set(), set()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'admitted.glb'
        path.write_bytes(raw)
        entry = {'sha256': digest, 'bytes': len(raw)}
        for iteration in range(args.repeats+1):
            gc.collect()
            def measured(name, fn):
                tracemalloc.start()
                tracemalloc.reset_peak()
                initial = tracemalloc.get_traced_memory()[0]
                start = time.perf_counter_ns()
                result = fn()
                duration = (time.perf_counter_ns()-start)/1e6
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                if iteration:
                    times[name].append(duration)
                    traced_peaks[name].append(max(0, peak-initial))
                return result

            file_bytes = measured('file_sha_read', path.read_bytes)
            if hashlib.sha256(file_bytes).hexdigest() != digest:
                raise AssertionError('STAGE_SOURCE_SHA_MISMATCH')
            info = measured('preflight_json_bin', lambda: inspect_glb(file_bytes))
            if info['meshes'] != 1:
                raise AssertionError('STAGE_CONTAINER_INVALID')
            doc, binary = measured('read_glb_io_json', lambda: read_glb(path, digest, len(raw)))
            positions = measured('typed_accessor_decode', lambda: accessor(doc, binary, 0))
            asset = measured('typed_import', lambda: load_asset(path, entry))
            if not np.array_equal(positions, asset['positions']):
                raise AssertionError('STAGE_TYPED_INPUT_MISMATCH')
            verts = [Vertex(np.asarray([*p, 1.], dtype=np.float32),
                            color=np.asarray([.8, .4, .2], dtype=np.float32))
                     for p in asset['positions']]
            faces = [tuple(map(int, f)) for f in asset['faces']]
            fb = Framebuffer(64, 64)
            renderer = SoftwareRasterizer(fb, backend='tiles', num_threads=1)
            def draw():
                fb.clear(16,25,38,255,depth=1.0)
                renderer.draw_mesh(verts, faces, VertexColorShader())
                return (hashlib.sha256(fb.color_buffer.tobytes()).hexdigest(),
                        hashlib.sha256(fb.depth_buffer.tobytes()).hexdigest())
            try:
                one = measured('first_draw', draw)
                two = measured('followup_draw', draw)
                if one != two:
                    raise AssertionError('STAGE_DRAW_RGBA_FLOAT32_DEPTH_DIFFER')
                rgba.add(one[0]); depths.add(one[1])
            finally:
                renderer.executor.shutdown(wait=True)
            def release():
                nonlocal doc, binary, positions, asset, file_bytes, fb, renderer, verts, faces
                del doc, binary, positions, asset, file_bytes, fb, renderer, verts, faces
                gc.collect()
            measured('release_gc', release)
    if len(rgba) != 1 or len(depths) != 1:
        raise AssertionError('STAGE_FRAME_REPLAY_NOT_DETERMINISTIC')
    root = Path(__file__).resolve().parents[2]
    paths = [Path(__file__).resolve(),
             Path(inspect_glb.__code__.co_filename).resolve(),
             Path(read_glb.__code__.co_filename).resolve(),
             Path(make_resource_glb.__code__.co_filename).resolve()]
    report = dict(protocol='are.glb-import-stage-profile.v1', source_revision=subprocess.check_output(
                     ['git','rev-parse','HEAD'], cwd=root, text=True).strip(),
                  asset_sha256=digest, asset_bytes=len(raw), synthetic_fixture=True,
                  imported_meshes=1, multi_mesh_native_import_supported=False,
                  cpu_model=platform.processor() or platform.machine(),
                  python=platform.python_version(), numpy=np.__version__,
                  affinity=sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,
                  source_paths_sha256={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                  repeats=args.repeats,
                  times_ms={name:dict(raw=values, stats=stat(values)) for name, values in times.items()},
                  traced_alloc_bytes={name:dict(raw=values, stats=stat(values)) for name, values in traced_peaks.items()},
                  process_rss_snapshot=rss_status(),
                  process_rss_semantics='process_cumulative_high_water_not_stage_attribution',
                  io_cache_semantics='filesystem_page_cache_uncontrolled_not_cold_io',
                  stages_independent_not_additive=True,
                  rgba8_sha256=next(iter(rgba)), depth_float32_sha256=next(iter(depths)),
                  gpu_or_fps_evidence=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False)+'\n')
    print('GLB_IMPORT_STAGES_REPLAY_OK', report['asset_sha256'], len(times), args.repeats)


if __name__ == '__main__':
    main()