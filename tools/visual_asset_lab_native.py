"""Offline native AREMDL03 beauty and source-derived three-view asset diagnostics.

The sole beauty/depth authority is the existing C++17 model probe. Wireframe
and UV seams are non-occluded geometry overlays calculated from its source poses.
No URI or external material source is ever resolved, and no HTTP UI is exposed.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np
from PIL import Image

from software_gpu.learning import configured_learner
from software_gpu.research.model_probe import (
    build_model_probe, load_asset, read_glb, run_model, write_scene,
)

PROTOCOL = 'are.visual-asset-lab.native.v1'
ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}$')
MAX_ASSETS = 8
MAX_OVERLAY_TRIANGLES = 50000


def _need(valid: bool, code: str) -> None:
    if not valid:
        raise ValueError('ASSET_LAB_' + code)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _material_evidence(doc: dict, binary: memoryview) -> tuple[list[dict], list[dict]]:
    materials = []
    for i, record in enumerate(doc.get('materials', [])):
        materials.append({'index': i, 'sha256': _sha(_canonical(record)),
                          'alpha_mode': record.get('alphaMode', 'OPAQUE'),
                          'double_sided': record.get('doubleSided', False)})
    images = []
    views = doc.get('bufferViews', [])
    for i, image in enumerate(doc.get('images', [])):
        _need(isinstance(image, dict) and 'uri' not in image and 'bufferView' in image,
              'EMBEDDED_IMAGES_ONLY')
        vi = image['bufferView']
        _need(type(vi) is int and 0 <= vi < len(views), 'IMAGE_VIEW')
        view = views[vi]
        offset, size = view.get('byteOffset', 0), view.get('byteLength')
        _need(type(offset) is int and type(size) is int and offset >= 0 and size > 0
              and offset + size <= len(binary) and view.get('buffer', 0) == 0,
              'IMAGE_BOUNDS')
        images.append({'index': i, 'sha256': _sha(bytes(binary[offset:offset + size])),
                       'mime_type': image.get('mimeType'), 'bytes': size})
    return materials, images


def _prepare_samples(samples: list[dict]) -> list[dict]:
    _need(type(samples) is list and 1 <= len(samples) <= MAX_ASSETS,
          'SOURCE_COUNT')
    prepared = []
    seen = set()
    for record in samples:
        _need(isinstance(record, dict) and set(record) ==
              {'id', 'path', 'sha256', 'bytes'}, 'SOURCE_FIELDS')
        identifier, name = record['id'], record['path']
        _need(isinstance(identifier, str) and ID.fullmatch(identifier) is not None
              and identifier not in seen, 'SOURCE_ID')
        seen.add(identifier)
        _need(isinstance(name, str) and name and '://' not in name
              and not name.startswith('file:'), 'LOCAL_FILE')
        path = Path(name)
        _need(not path.is_symlink() and path.is_file() and path.suffix.lower() == '.glb',
              'LOCAL_FILE')
        expected = {'sha256': record['sha256'], 'bytes': record['bytes']}
        _need(type(record['sha256']) is str and
              re.fullmatch('[0-9a-f]{64}', record['sha256']) is not None
              and type(record['bytes']) is int, 'SOURCE_IDENTITY')
        # Existing admission binds every byte to its original full SHA-256.
        asset = load_asset(path, expected, profile='pbr')
        _need(not asset['clips'], 'STATIC_ONLY')
        _need(len(asset['faces']) <= MAX_OVERLAY_TRIANGLES, 'OVERLAY_TRIANGLE_BUDGET')
        doc, binary = read_glb(path, record['sha256'], record['bytes'])
        materials, images = _material_evidence(doc, binary)
        prepared.append(dict(id=identifier, source=record, asset=asset,
                             materials=materials, embedded_images=images,
                             source_name=path.name))
    return prepared


def _native_pose(executable: Path, request: Path, count: int) -> np.ndarray:
    result = run_model(executable, request, workers=1, repeats=1,
                       mode='pose', render_profile='pbr')
    poses = result['poses']
    _need(len(poses) == 1 and len(poses[0]) == 1, 'POSE_SHAPE')
    vertices = np.asarray(poses[0][0], dtype='<f8')
    _need(vertices.shape == (count, 3) and np.isfinite(vertices).all(), 'POSE_SHAPE')
    return vertices


def _native_framing(raw_pose: np.ndarray) -> tuple[np.ndarray, dict]:
    # Mirrors Model::normalize, Model::pose and Scene::fit from model_scene.hpp.
    low, high = raw_pose.min(axis=0), raw_pose.max(axis=0)
    span = float((high - low).max())
    _need(span > 1e-12, 'BOUNDS')
    local_center = (low + high) * .5
    local_scale = 2.0 / span
    p = (raw_pose - local_center) * local_scale
    cy, sy = math.cos(.45), math.sin(.45)
    cx, sx = math.cos(-.18), math.sin(-.18)
    x = cy * p[:, 0] + sy * p[:, 2]
    z = -sy * p[:, 0] + cy * p[:, 2]
    y = cx * p[:, 1] - sx * z
    q = np.column_stack([x, y, sx * p[:, 1] + cx * z])
    scene_low, scene_high = q.min(axis=0), q.max(axis=0)
    scene_span = float((scene_high - scene_low).max())
    _need(scene_span > 1e-12, 'BOUNDS')
    scene_center = (scene_low + scene_high) * .5
    scene_scale = 1.8 / scene_span
    normalized = (q - scene_center) * scene_scale
    return normalized, dict(local_center=local_center.tolist(),
                            local_scale=local_scale,
                            scene_center=scene_center.tolist(),
                            scene_scale=scene_scale)


def _project(points: np.ndarray, camera: dict, pixels: int) -> list[tuple[float, float] | None]:
    eye = np.asarray(camera['eye'], dtype='<f8')
    target = np.asarray(camera['target'], dtype='<f8')
    up = np.asarray(camera['up'], dtype='<f8')
    forward = target - eye
    forward /= np.linalg.norm(forward)
    up /= np.linalg.norm(up)
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    real_up = np.cross(right, forward)
    focal = 1.0 / math.tan(math.radians(camera['fov_y_degrees']) * .5)
    relative = points - eye
    vx, vy, distance = relative @ right, relative @ real_up, relative @ forward
    result = []
    for xx, yy, dd in zip(vx, vy, distance):
        if dd <= camera['near'] or dd >= camera['far']:
            result.append(None)
            continue
        nx, ny = focal * xx / dd, focal * yy / dd
        result.append(((nx + 1.0) * .5 * pixels,
                       (1.0 - ny) * .5 * pixels))
    return result


def _seam_edges(asset: dict) -> tuple[list[tuple[int, int]], int]:
    # Shared source-space geometric edges with differing endpoint UV mappings.
    xyz, uv, faces = asset['positions'], asset['uvs'], asset['faces']
    edges: dict[tuple[bytes, bytes], list[tuple[tuple[bytes, bytes], tuple[int, int]]]] = {}
    for a, b, c in faces:
        for p, q in ((int(a), int(b)), (int(b), int(c)), (int(c), int(a))):
            vp, vq = xyz[p].tobytes(), xyz[q].tobytes()
            if vp == vq:
                continue
            if vp > vq:
                p, q, vp, vq = q, p, vq, vp
            edges.setdefault((vp, vq), []).append(((uv[p].tobytes(), uv[q].tobytes()), (p, q)))
    seams = []
    for candidates in edges.values():
        if len(candidates) > 1 and len({pair for pair, _ in candidates}) > 1:
            seams.append(candidates[0][1])
    return seams, len(edges)


def _vector_svg(points, faces, *, pixels, seam_mode=False) -> tuple[bytes, int]:
    rows = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{pixels}" height="{pixels}" viewBox="0 0 {pixels} {pixels}">',
            f'<rect width="{pixels}" height="{pixels}" fill="#0d1725"/>']
    skipped = 0
    for row in faces:
        positions = [points[int(index)] for index in row]
        if any(p is None for p in positions):
            skipped += 1
            continue
        path = ' '.join(('M' if i == 0 else 'L') + f'{xy[0]:.4f},{xy[1]:.4f}'
                        for i, xy in enumerate(positions))
        if not seam_mode:
            path += ' Z'
        rows.append(f'<path d="{path}" fill="none" stroke="{("#ffac6b" if seam_mode else "#65d5de")}" stroke-width=".85"/>')
    rows.append('</svg>')
    return ('\n'.join(rows) + '\n').encode('utf-8'), skipped


def _artifact(folder: Path, name: str, data: bytes, *, semantics: str) -> dict:
    (folder / name).write_bytes(data)
    return dict(filename=name, sha256=_sha(data), bytes=len(data), semantics=semantics)


def render_native_asset_lab(samples: list[dict], output_dir: Path, *,
                            camera: dict, pixels: int = 64, repeats: int = 2) -> dict:
    """Run SHA-pinned C++ PBR for one or more LODs, comparing workers 1 and 2.

    This is parity/diagnostic evidence, NOT a CPU performance leaderboard entry.
    Requires a fresh output directory and only trusted local, explicit GLB paths.
    """
    target = Path(output_dir)
    _need(not target.is_symlink() and not target.exists() and target.parent.is_dir(),
          'OUTPUT')
    _need(type(pixels) is int and 16 <= pixels <= 512
          and type(repeats) is int and 2 <= repeats <= 5, 'RENDER_BUDGET')
    prepared = _prepare_samples(samples)  # no output files created on rejection
    with tempfile.TemporaryDirectory(prefix='are-visual-native-') as tmp:
        working = Path(tmp)
        executable, build = build_model_probe(working / 'build')
        planned = []
        for index, record in enumerate(prepared):
            request = working / f'scene-{index}.aremdl'
            request_receipt = write_scene(request, [dict(asset=record['asset'], clip=None)],
                                          [0.0], pixels=pixels, tile=16,
                                          projection='perspective', camera=camera,
                                          render_profile='pbr')
            posed = _native_pose(executable, request, len(record['asset']['positions']))
            vertices, framing = _native_framing(posed)
            planned.append(dict(record=record, request=request,
                                request_receipt=request_receipt,
                                vertices=vertices, framing=framing))
        # The native Scene::fit is automatic per input. Revisions with different
        # fits cannot be ranked as an identical-camera/effective-scale comparison.
        base = _canonical(planned[0]['framing'])
        shared_fit = all(_canonical(p['framing']) == base for p in planned)
        # Scene::fit runs separately for each source mesh. A matching camera
        # does not imply identical effective model normalization across LODs.
        stage = working / 'export'
        stage.mkdir()
        artifacts = []
        for item in planned:
            record = item['record']
            ref = run_model(executable, item['request'], workers=1,
                            repeats=repeats, render_profile='pbr')
            other = run_model(executable, item['request'], workers=2,
                              repeats=repeats, render_profile='pbr')
            _need(all(np.array_equal(ref[k], other[k])
                      for k in ('frames', 'resolved', 'depth')),
                  'NATIVE_WORKER_BUFFER_MISMATCH')
            # Preserve explicit 1/2-worker proofs. For local learning-enabled
            # authoring jobs, a third opt-in run may select a separately
            # hash-verified native worker variant; it cannot replace parity.
            selected = other
            learning = None
            if configured_learner() is not None:
                selected = run_model(executable, item['request'], workers='auto',
                                     repeats=repeats, render_profile='pbr')
                _need(all(np.array_equal(ref[k], selected[k])
                          for k in ('frames', 'resolved', 'depth')),
                      'LEARNED_NATIVE_WORKER_BUFFER_MISMATCH')
                learning = selected['learning']
            _need(other['receipt']['full_buffer_parity'] is True
                  and other['receipt']['serial_reference_first_frame'] is True,
                  'NATIVE_PARITY_RECEIPT')
            actual = selected['receipt']
            _need(any(writes > 0 for writes in actual['sample_writes']),
                  'NATIVE_NO_FRAGMENTS')
            _need(actual['camera_eye'] == camera['eye'] and
                  actual['camera_target'] == camera['target'] and
                  actual['camera_up'] == camera['up'] and
                  actual['fov_y_degrees'] == camera['fov_y_degrees'] and
                  actual['near_plane'] == camera['near'] and
                  actual['far_plane'] == camera['far'], 'NATIVE_CAMERA')
            where = stage / record['id']
            where.mkdir()
            rgba = selected['resolved'].tobytes()
            depth = np.asarray(selected['depth'], dtype='<f4').tobytes()
            image = Image.fromarray(selected['resolved'], mode='RGBA')
            png, bmp = io.BytesIO(), io.BytesIO()
            image.save(png, format='PNG')
            image.save(bmp, format='BMP')
            seam, edge_count = _seam_edges(record['asset'])
            projected = _project(item['vertices'], camera, pixels)
            wire, dropped = _vector_svg(projected, record['asset']['faces'], pixels=pixels)
            uv, seam_dropped = _vector_svg(projected, seam, pixels=pixels, seam_mode=True)
            output = {
                'beauty_png': _artifact(where, 'beauty.png', png.getvalue(),
                                        semantics='native_aremdl03_resolved_rgba8_encoded_png'),
                'beauty_bmp': _artifact(where, 'beauty.bmp', bmp.getvalue(),
                                        semantics='native_aremdl03_resolved_rgba8_encoded_bmp'),
                'rgba8': _artifact(where, 'native-rgba8.bin', rgba,
                                   semantics='cpp17_aremdl03_resolved_framebuffer_rgba8'),
                'depth_f32le': _artifact(where, 'native-depth.f32le', depth,
                                         semantics='cpp17_aremdl03_final_depth_float32_le'),
                'wireframe_svg': _artifact(where, 'wireframe.svg', wire,
                                           semantics='source_derived_native_pose_nonoccluded_edges'),
                'uv_seams_svg': _artifact(where, 'uv_seams.svg', uv,
                                          semantics='source_derived_native_pose_nonoccluded_uv_discontinuities'),
            }
            artifacts.append(dict(id=record['id'], source_sha256=record['source']['sha256'],
                                  source_bytes=record['source']['bytes'],
                                  source_name=record['source_name'],
                                  source_triangle_count=len(record['asset']['faces']),
                                  camera=request_receipt['camera'], framing=item['framing'],
                                  input_sha256=request_receipt['sha256'],
                                  materials=record['materials'],
                                  embedded_images=record['embedded_images'],
                                  shadow_status='not_implemented',
                                  normal_status='source_normals',
                                  material_status='opaque_gltf_metallic_roughness_native',
                                  uv_seam_count=len(seam), source_edge_count=edge_count,
                                  wireframe_edges_unclipped_skipped=dropped,
                                  seam_edges_unclipped_skipped=seam_dropped,
                                  artifacts=output,
                                  renderer=dict(protocol=actual['protocol'],
                                                render_profile=actual['render_profile'],
                                                full_buffer_parity=True,
                                                worker_counts=[1, 2],
                                                sample_writes=actual['sample_writes'],
                                                compiler_build_sha256=build['binary_sha256'],
                                                source_code_sha256=build['source_sha256'],
                                                response_sha256=actual['response_sha256'],
                                                learning=learning)))
        receipt = dict(protocol=PROTOCOL, authority='native_cpp17_aremdl03',
                       camera=planned[0]['request_receipt']['camera'],
                       pixels=pixels,
                       comparability=dict(
                           status=('same_native_fit_and_camera' if shared_fit else
                                   'same_camera_different_native_fit_not_visually_equivalent'),
                           native_auto_fit_equal=shared_fit,
                           performance='not_ranked_or_benchmarked',
                           independent_lod_timing='not_performed'),
                       views=dict(beauty='native_pbr', wireframe='derived_not_occlusion_tested',
                                  uv_seams='derived_not_occlusion_tested'),
                       native_build=build, assets=artifacts,
                       security=dict(ui='none_local_cli_only', external_uris='rejected',
                                     source_sha256_required=True))
        (stage / 'receipt.json').write_bytes(
            json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False).encode('utf-8') + b'\n')
        # All native runs, worker comparisons and receipts completed before publish.
        _need(not target.exists() and not target.is_symlink(), 'OUTPUT')
        shutil.move(str(stage), str(target))
        return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path, help='Local manifest with SHA-pinned GLBs')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--pixels', type=int, default=64)
    args = parser.parse_args(argv)
    try:
        if args.manifest.is_symlink() or not args.manifest.is_file() or args.manifest.stat().st_size > 65536:
            raise ValueError('ASSET_LAB_MANIFEST_FILE')
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        _need(isinstance(manifest, dict) and set(manifest) == {'assets', 'camera'},
              'MANIFEST_FIELDS')
        render_native_asset_lab(manifest['assets'], args.output_dir,
                                camera=manifest['camera'], pixels=args.pixels)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(2, f'ASSET_LAB_REJECTED:{exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
