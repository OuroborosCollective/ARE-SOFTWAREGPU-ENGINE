#!/usr/bin/env python3
"""Original GLB workloads, independent pose validation and paired native timings.

Python prepares one typed input and launches a C++ process. No Python executes
inside the native pose/project/render/MSAA/AA loop. Original assets stay local.
"""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from software_gpu.research.model_probe import build_model_probe, load_asset, write_scene, run_model, SOURCES
from software_gpu.research.bio_workrooms import POLICIES
from tools.model_reference import pose
from tools.benchmark_bio_workrooms import stats, environment

COLORS = dict(mage=[145,110,245,255], assassin=[235,115,165,255], axe=[75,205,190,255],
              sword=[235,165,60,255], log=[145,100,65,255], boulder=[155,165,180,255],
              crystal=[100,215,245,255], wisteria=[145,190,120,255], armor=[210,85,60,255])
CLIPS = dict(mage='Charged_Spell_Cast', assassin='Dodge_and_Counter', axe='Axe_Spin_Attack', sword='Sword_Judgment')
ORDER = ('mage','assassin','axe','sword','log','boulder','crystal','armor','wisteria')
# Keep the workload's temporal distribution independent of the requested number
# of measurement pairs. Repeats may change for statistical runs, but the same
# first 15 frame poses must remain the same reference workload.
REFERENCE_PHASES = np.linspace(0.0, 1.0, 15).tolist()


def reference_sample_times(duration, repeats):
    """Return a stable, cyclic set of normalized reference timestamps."""
    if duration < 0 or repeats < 1:
        raise ValueError('duration and repeats must be positive')
    return [duration * REFERENCE_PHASES[i % len(REFERENCE_PHASES)] for i in range(repeats)]


def hashes():
    files = [f'native/symbolic/{n}' for n in SOURCES] + ['software_gpu/research/model_probe.py',
       'software_gpu/research/model_material_import.py','tools/model_reference.py','tools/model_surface_reference.py',
       'tools/benchmark_models.py','evidence/original-model-manifest-v1.json']
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files}


def placement(x=0, y=0, z=0, scale=1, yaw=0):
    c, s = np.cos(yaw), np.sin(yaw)
    return np.array([[scale*c,0,scale*s,x],[0,scale,0,y],[-scale*s,0,scale*c,z],[0,0,0,1]])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assets', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--phase', choices=('poses','bench','all'), default='all')
    p.add_argument('--projection', choices=('orthographic','perspective'), default='orthographic',
                   help='perspective selects AREMDL02 with explicit camera and native homogeneous clipping')
    p.add_argument('--render-profile', choices=('diagnostic','pbr'), default='diagnostic',
                   help='pbr selects AREMDL03 perspective-correct UVs, glTF textures and Cook-Torrance shading')
    p.add_argument('--bio-policy', choices=POLICIES, default='combined',
                   help='native Bio scheduler policy; locality avoids frontier/checkpoint overhead for large PBR scenes')
    p.add_argument('--repeats', type=int, default=15)
    p.add_argument('--seconds', type=int, default=1800)
    p.add_argument('--cases', help='comma-separated case names: animated4, static2, arena6, all9, or individual aliases')
    a = p.parse_args()
    if not 15 <= a.repeats <= 30 or not 1 <= a.seconds <= 3600:
        p.error('15..30 pairs and 1..3600 second total budget required')
    if a.render_profile=='pbr' and a.projection!='perspective':
        p.error('--render-profile pbr requires --projection perspective')
    output = Path(a.output_dir).resolve(); output.mkdir(parents=True, exist_ok=True)
    start = time.monotonic(); before = hashes()
    manifest = json.loads((ROOT/'evidence/original-model-manifest-v1.json').read_text())
    entries = {e['alias']: e for e in manifest['files'] if 'duplicate_of' not in e}
    used_aliases = set()
    exe, build = build_model_probe(output/'native')
    report = dict(protocol='are.original-model-benchmark.v1', phase=a.phase, environment=environment(), build=build,
        source_sha256_before=before, source_sha256_after=None, originals_modified=False,
        config=dict(pixels=256, tile=32, workers=4, repeats=a.repeats, warmups=3, paired_order='alternating',
                    policy=a.bio_policy, projection=a.projection,render_profile=a.render_profile,
                    camera=('AREMDL02 explicit view/projection; default eye=(0,0,4), target=(0,0,0), fov_y=43deg, near=0.1, far=80'
                            if a.projection=='perspective' else 'fixed orthographic fit over declared sample times')),
        scope=dict(shader=('opaque double-sided per-face diagnostic lighting; original textures/PBR ignored'
                           if a.render_profile=='diagnostic' else 'opaque glTF metallic-roughness; perspective-correct UV/normal/world interpolation; basecolor, normal and MR maps; Cook-Torrance/GGX'),
                   native_frame=('skin + pose + projection + diagnostic lighting + raster + 4x byte-RGBA MSAA + FXAA'
                                 if a.render_profile=='diagnostic' else 'skin + pose + homogeneous clip + perspective-correct UV/normal/world interpolation + texture sampling/mips + GGX shading + linear 4x MSAA + Reinhard/sRGB + FXAA'),
                   baseline='current scalar Pipeline with explicit model admission; original 64-triangle ABI is unchanged',
                   excluded='GLB load, typed input, cold fit/construction/reference, parity checks and frame serialization',
                   hardware_gpu=False, combat_ai=False, thermal_measurements=None), poses=[], cases=[])

    def checkpoint():
        report['elapsed_seconds'] = time.monotonic()-start
        (output/'benchmark.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')

    def remaining():
        seconds = int(a.seconds-(time.monotonic()-start))
        if seconds < 1:
            raise TimeoutError('overall benchmark budget exhausted')
        return min(1800, seconds)

    if a.phase in ('poses','all'):
        for alias in ORDER[:4]:
            used_aliases.add(alias)
            asset = load_asset(Path(a.assets)/entries[alias]['file'], entries[alias])
            for ci, clip in enumerate(asset['clips']):
                sample_times = [0.0, .25*clip['duration'], .5*clip['duration'], .75*clip['duration'], clip['duration']]
                request = output/'pose-input.bin'
                metadata = write_scene(request, [dict(asset=asset,clip=ci)], sample_times)
                actual = run_model(exe, request, mode='pose', timeout=remaining())
                errors = [float(np.max(np.abs(frame[0]-pose(asset,ci,t)))) for frame,t in zip(actual['poses'],sample_times)]
                if max(errors) > 1e-8:
                    raise AssertionError(('POSE_ORACLE_MISMATCH', alias, clip['name'], errors))
                report['poses'].append(dict(asset=alias, source_sha256=entries[alias]['sha256'], clip=clip['name'],
                    vertices=len(asset['positions']), times=sample_times, maximum_absolute_error=errors,
                    input=metadata, response_sha256=actual['response_sha256']))
                print('POSE',alias,clip['name'],max(errors),flush=True)
            del asset, actual
            gc.collect(); checkpoint()
        request.unlink()
    if a.phase in ('bench','all'):
        scene_sets = {'animated4':list(ORDER[:4]),'static2':list(ORDER[4:6]),
                      'arena6':list(ORDER[:6]),'all9':list(ORDER)}
        if a.cases:
            requested=[value.strip() for value in a.cases.split(',') if value.strip()]
            unknown=sorted(set(requested)-set(ORDER)-set(scene_sets))
            if not requested or unknown:p.error(f'unknown or empty --cases values: {unknown}')
            specs=[(name,scene_sets[name]) if name in scene_sets else (name,[name]) for name in requested]
        else:
            specs=[(alias,[alias]) for alias in ORDER]+[(name,scene_sets[name]) for name in ('arena6','all9')]
        for name, aliases in specs:
            used_aliases.update(aliases)
            load_start = time.monotonic()
            assets = {alias: load_asset(Path(a.assets)/entries[alias]['file'], entries[alias],profile=a.render_profile) for alias in aliases}
            instances = []
            # Fixed placements and clips are chosen before measurements, not tuned to timings.
            for i, alias in enumerate(aliases):
                asset = assets[alias]
                clip = next((j for j,c in enumerate(asset['clips']) if c['name']==CLIPS.get(alias)), None)
                m = np.eye(4)
                if len(aliases) > 1:
                    transforms = dict(mage=(-1.25,0,-.7,1,0), assassin=(1.25,0,-.7,1,3.14),
                        axe=(-1.25,0,1.3,1,0), sword=(1.25,0,1.3,1,3.14),
                        log=(-2.7,-.8,2.7,.7,.4), boulder=(2.6,-.7,2.5,.8,0),
                        crystal=(-3.1,.1,-2.5,1.1,0), armor=(3.1,.2,-2.5,1.25,0),
                        wisteria=(0,1.2,-4,2.4,0))
                    m = placement(*transforms[alias])
                instances.append(dict(asset=asset,clip=clip,color=COLORS[alias],placement=m))
            duration = (max(assets[x]['clips'][instances[i]['clip']]['duration'] for i,x in enumerate(aliases)
                            if instances[i]['clip'] is not None) if any(x['clip'] is not None for x in instances) else 0)
            sample_times = reference_sample_times(duration, a.repeats)
            request = output/'render-input.bin'
            metadata = write_scene(request, instances, sample_times, projection=a.projection,render_profile=a.render_profile)
            load_ms = 1000*(time.monotonic()-load_start)
            del assets, instances, asset
            gc.collect()
            print('RENDER_START',name,metadata['triangles'],flush=True)
            try:
                result = run_model(exe, request, workers=4, repeats=a.repeats, policy=a.bio_policy,
                                   timeout=remaining(),render_profile=a.render_profile)
                receipt = result['receipt']
                if (receipt['triangles'] != metadata['triangles'] or receipt['vertices'] != metadata['vertices']
                        or receipt['projection'] != metadata['projection']
                        or receipt['render_profile'] != metadata['render_profile']
                        or receipt['models'] != len(metadata['instances']) or result['frames'].shape != (a.repeats,256,256,4)):
                    raise AssertionError('MODEL_REQUEST_RECEIPT_MISMATCH')
                summary = {key:stats(value) for key,value in receipt.items() if key.endswith('_ms') and isinstance(value,list)}
                summary['paired_total_speedup'] = stats([b/c for b,c in zip(receipt['baseline_total_ms'],receipt['candidate_total_ms'])])
                summary['ratio_of_median_total'] = summary['baseline_total_ms']['median']/summary['candidate_total_ms']['median']
                summary['ratio_of_median_render'] = summary['baseline_render_ms']['median']/summary['candidate_render_ms']['median']
                timing_fields=('animated_pose_ms','static_pose_ms','triangle_prepare_ms','handoff_ms',
                    'render_setup_ms','rasterization_ms','msaa_ms','aa_ms','scheduler_binning_ms','frame_total_ms',
                    'render_setup_worker_work_ms','rasterization_worker_work_ms','msaa_worker_work_ms','aa_worker_work_ms')
                summary['candidate_frame_stages']={field:stats([frame[field] for frame in receipt['candidate_frame_timings']])
                                                   for field in timing_fields}
                summary['baseline_frame_stages']={field:stats([frame[field] for frame in receipt['baseline_frame_timings']])
                                                  for field in timing_fields}
                summary['frame_budget_ms']=16.7
                summary['candidate_slow_frames']=[{'frame':frame['frame'],'frame_total_ms':frame['frame_total_ms']}
                    for frame in receipt['candidate_frame_timings'] if frame['frame_total_ms']>16.7]
                summary['candidate_slowest_frames']=sorted(
                    ({'frame':frame['frame'],'frame_total_ms':frame['frame_total_ms']} for frame in receipt['candidate_frame_timings']),
                    key=lambda frame:frame['frame_total_ms'],reverse=True)[:min(5,a.repeats)]
                np.savez_compressed(output/(name+'-frames.npz'), frames=result['frames'], resolved=result['resolved'], depth=result['depth'])
                case = dict(name=name,status='measured',input=metadata,offline_load_and_pack_ms=load_ms,receipt=receipt,summary=summary)
                report['cases'].append(case)
                print('RENDER_OK',name,'total speedup',summary['ratio_of_median_total'], 'candidate_ms',summary['candidate_total_ms']['median'],flush=True)
                del result
            except (RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
                report['cases'].append(dict(name=name,status='failed',input=metadata,error=str(exc)))
                checkpoint()
                raise
            request.unlink(); checkpoint()
    report['source_sha256_after'] = hashes()
    if report['source_sha256_after'] != before:
        raise AssertionError('SOURCE_DRIFT')
    measured_entries=[entries[alias] for alias in sorted(used_aliases)]
    report['original_sha256_after'] = {e['file']:hashlib.sha256((Path(a.assets)/e['file']).read_bytes()).hexdigest() for e in measured_entries}
    if any(report['original_sha256_after'][e['file']] != e['sha256'] for e in measured_entries):
        raise AssertionError('ORIGINAL_SOURCE_DRIFT')
    checkpoint()


if __name__ == '__main__':
    main()
