"""Pinned GLB -> typed offline input. Animation, shading and rendering run in C++17.

Admitted subset: one indexed triangle primitive/instance, opaque double-sided
geometry, optional one skin with all 1..3 influence sets, TRS/matrix nodes and
STEP/LINEAR TRS animation. This diagnostic renderer does not evaluate textures.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import numpy as np
from .native_symbolic import FLAGS, NATIVE, compiler

MAX_BYTES = 256 * 1024 * 1024
DTYPES = {5121: '<u1', 5123: '<u2', 5125: '<u4', 5126: '<f4'}
DIMS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
SOURCES = ('core.hpp', 'workrooms.hpp', 'workrooms_wire.hpp', 'bio_workrooms.hpp', 'model_scene.hpp', 'model_main.cpp')


def require(ok, code):
    if not ok:
        raise ValueError(code)


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'MODEL_JSON_DUPLICATE')
        result[key] = value
    return result


def _uint(value, hi, lo=0):
    require(type(value) is int and lo <= value <= hi, 'MODEL_INTEGER')
    return value


def _vec(value, n):
    a = np.asarray(value, dtype='<f8')
    require(a.shape == (n,) and np.isfinite(a).all() and (np.abs(a) <= 1e12).all(), 'MODEL_VECTOR')
    return a


def read_glb(path, expected_sha256, expected_bytes):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), 'MODEL_SOURCE_FILE')
    require(32 <= expected_bytes <= MAX_BYTES and path.stat().st_size == expected_bytes, 'MODEL_SOURCE_SIZE')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'MODEL_SOURCE_HASH')
    require(struct.unpack_from('<4sII', raw) == (b'glTF', 2, len(raw)), 'MODEL_GLB_HEADER')
    chunks, offset = [], 12
    while offset < len(raw):
        require(offset + 8 <= len(raw), 'MODEL_GLB_CHUNK')
        length, kind = struct.unpack_from('<I4s', raw, offset)
        offset += 8
        require(len(chunks) < 2 and length > 0 and length % 4 == 0
                and offset + length <= len(raw), 'MODEL_GLB_CHUNK')
        chunks.append((kind, memoryview(raw)[offset:offset+length]))
        offset += length
    require(len(chunks) == 2 and [c[0] for c in chunks] == [b'JSON', b'BIN\0'], 'MODEL_GLB_CHUNKS')
    require(len(chunks[0][1]) <= 2*1024*1024, 'MODEL_JSON_BUDGET')
    doc = json.loads(bytes(chunks[0][1]), object_pairs_hook=_object,
                     parse_constant=lambda _: require(False, 'MODEL_JSON_NONFINITE'))
    require(doc.get('asset', {}).get('version') == '2.0' and not doc.get('extensionsRequired'), 'MODEL_GLTF_VERSION_OR_EXTENSION')
    buffers = doc.get('buffers', [])
    require(len(buffers) == 1 and 'uri' not in buffers[0], 'MODEL_EXTERNAL_BUFFER')
    length = _uint(buffers[0]['byteLength'], len(chunks[1][1]), 1)
    require(len(chunks[1][1])-length <= 3, 'MODEL_BUFFER_PADDING')
    return doc, chunks[1][1][:length]


def accessor(doc, binary, index):
    a = doc['accessors'][_uint(index, len(doc['accessors'])-1)]
    require('sparse' not in a and a.get('type') in DIMS and a.get('componentType') in DTYPES, 'MODEL_ACCESSOR_ENCODING')
    dtype, dims = np.dtype(DTYPES[a['componentType']]), DIMS[a['type']]
    count = _uint(a['count'], 24000000, 1)
    view = doc['bufferViews'][_uint(a['bufferView'], len(doc['bufferViews'])-1)]
    require(view.get('buffer', 0) == 0, 'MODEL_BUFFER_INDEX')
    base = _uint(view.get('byteOffset', 0), len(binary))
    size = _uint(view['byteLength'], len(binary))
    inner = _uint(a.get('byteOffset', 0), size)
    stride = _uint(view.get('byteStride', dims*dtype.itemsize), 256, dims*dtype.itemsize)
    require(base+size <= len(binary) and inner+(count-1)*stride+dims*dtype.itemsize <= size
            and (base+inner) % dtype.itemsize == 0 and stride % dtype.itemsize == 0, 'MODEL_ACCESSOR_BOUNDS')
    out = np.ndarray((count, dims), dtype=dtype, buffer=binary, offset=base+inner,
                     strides=(stride, dtype.itemsize)).copy()
    if a.get('normalized', False):
        require(a['componentType'] in (5121, 5123), 'MODEL_NORMALIZED_TYPE')
        out = out.astype('<f4') / np.iinfo(dtype).max
    return out


def load_asset(path, entry):
    doc, binary = read_glb(path, entry['sha256'], entry['bytes'])
    meshes, nodes = doc.get('meshes', []), doc.get('nodes', [])
    require(len(meshes) == 1 and len(meshes[0]['primitives']) == 1 and 1 <= len(nodes) <= 256, 'MODEL_MESH_SUBSET')
    instances = [i for i, n in enumerate(nodes) if 'mesh' in n]
    require(len(instances) == 1 and nodes[instances[0]]['mesh'] == 0, 'MODEL_INSTANCE_SUBSET')
    mesh_node = instances[0]
    primitive = meshes[0]['primitives'][0]
    require(primitive.get('mode', 4) == 4 and 'indices' in primitive and not primitive.get('targets')
            and not primitive.get('extensions') and not meshes[0].get('weights'), 'MODEL_PRIMITIVE_SUBSET')
    attrs = primitive['attributes']
    xyz, indices = accessor(doc, binary, attrs['POSITION']), accessor(doc, binary, primitive['indices'])
    require(xyz.dtype == np.dtype('<f4') and xyz.shape[1] == 3 and 1 <= len(xyz) <= 6100000
            and np.isfinite(xyz).all() and (np.abs(xyz) < 1e12).all(), 'MODEL_POSITIONS')
    require(indices.dtype.kind == 'u' and indices.shape[1] == 1 and len(indices) % 3 == 0
            and len(indices)//3 <= 8000000 and int(indices.max()) < len(xyz), 'MODEL_INDICES')
    faces = np.asarray(indices.reshape(-1, 3), dtype='<u4')
    parents = np.full(len(nodes), -1, dtype='<i4')
    for i, n in enumerate(nodes):
        for child in n.get('children', []):
            child = _uint(child, len(nodes)-1)
            require(parents[child] == -1 and child != i, 'MODEL_NODE_PARENT')
            parents[child] = i
    for i in range(len(nodes)):
        seen = set()
        while i != -1:
            require(i not in seen, 'MODEL_NODE_CYCLE')
            seen.add(i)
            i = int(parents[i])
    scenes = doc.get('scenes', [])
    scene = scenes[_uint(doc.get('scene', 0), len(scenes)-1)]
    reachable, todo = set(), list(scene.get('nodes', []))
    while todo:
        node = _uint(todo.pop(), len(nodes)-1)
        require(node not in reachable, 'MODEL_SCENE_TREE')
        reachable.add(node)
        todo.extend(nodes[node].get('children', []))
    require(mesh_node in reachable, 'MODEL_SCENE_MESH')
    typed_nodes = []
    for i, node in enumerate(nodes):
        item = {'parent': int(parents[i])}
        if 'matrix' in node:
            require(not any(k in node for k in ('translation', 'rotation', 'scale')), 'MODEL_NODE_MATRIX_TRS')
            m = _vec(node['matrix'], 16).reshape(4, 4).T.copy()
            require(np.array_equal(m[3], [0, 0, 0, 1]), 'MODEL_AFFINE_MATRIX')
            item['matrix'] = m
        else:
            item.update(t=_vec(node.get('translation', [0, 0, 0]), 3),
                        q=_vec(node.get('rotation', [0, 0, 0, 1]), 4),
                        s=_vec(node.get('scale', [1, 1, 1]), 3))
            require(np.linalg.norm(item['q']) > 1e-10, 'MODEL_QUATERNION')
        typed_nodes.append(item)
    skins = doc.get('skins', [])
    joints, ibm, joint_data, weights = [], np.empty((0, 4, 4), '<f8'), np.empty((len(xyz), 0), '<u4'), np.empty((len(xyz), 0), '<f4')
    sets = sorted(int(k.split('_')[1]) for k in attrs if re.fullmatch(r'JOINTS_\d+', k))
    wsets = sorted(int(k.split('_')[1]) for k in attrs if re.fullmatch(r'WEIGHTS_\d+', k))
    require(sets == wsets, 'MODEL_SKIN_ATTRIBUTE_PAIRS')
    if skins:
        require(len(skins) == 1 and nodes[mesh_node].get('skin') == 0 and sets in ([0], [0, 1], [0, 1, 2]), 'MODEL_SKIN_SUBSET')
        joints = skins[0]['joints']
        require(1 <= len(joints) <= 256 and len(set(joints)) == len(joints)
                and all(type(j) is int and j in reachable for j in joints), 'MODEL_JOINTS')
        ibm = accessor(doc, binary, skins[0]['inverseBindMatrices']) if 'inverseBindMatrices' in skins[0] else np.tile(np.eye(4).reshape(1, 16), (len(joints), 1))
        require(ibm.shape == (len(joints), 16) and np.isfinite(ibm).all(), 'MODEL_INVERSE_BIND')
        ibm = np.ascontiguousarray(ibm.reshape(-1, 4, 4).transpose(0, 2, 1), dtype='<f8')
        require(np.all(ibm[:, 3, :] == [0, 0, 0, 1]), 'MODEL_AFFINE_MATRIX')
        js, ws = [], []
        for k in sets:
            j, w = accessor(doc, binary, attrs[f'JOINTS_{k}']), accessor(doc, binary, attrs[f'WEIGHTS_{k}'])
            require(j.shape == w.shape == (len(xyz), 4) and j.dtype.kind == 'u' and int(j.max()) < len(joints)
                    and w.dtype.kind == 'f' and np.isfinite(w).all() and (w >= 0).all() and (w <= 1).all(), 'MODEL_WEIGHTS')
            js.append(j); ws.append(w)
        joint_data = np.ascontiguousarray(np.concatenate(js, axis=1), dtype='<u4')
        weights = np.ascontiguousarray(np.concatenate(ws, axis=1), dtype='<f4')
        require(float(np.abs(weights.astype('f8').sum(axis=1)-1).max()) < .001, 'MODEL_WEIGHT_SUM')
    else:
        require('skin' not in nodes[mesh_node] and not sets, 'MODEL_UNBOUND_SKIN')
    clips, total_keys = [], 0
    animations = doc.get('animations', [])
    require(len(animations) <= 64, 'MODEL_CLIP_BUDGET')
    for animation in animations:
        require(0 < len(animation['channels']) <= 3*len(nodes), 'MODEL_ANIMATION_CHANNELS')
        channels, targets = [], set()
        for channel in animation['channels']:
            target = channel['target']
            ni = _uint(target['node'], len(nodes)-1)
            prop = target.get('path')
            require(prop in ('translation', 'rotation', 'scale') and (ni, prop) not in targets
                    and 'matrix' not in typed_nodes[ni], 'MODEL_ANIMATION_TARGET')
            targets.add((ni, prop))
            sampler = animation['samplers'][_uint(channel['sampler'], len(animation['samplers'])-1)]
            method = sampler.get('interpolation', 'LINEAR')
            require(method in ('LINEAR', 'STEP'), 'MODEL_ANIMATION_INTERPOLATION')
            input_index = _uint(sampler['input'], len(doc['accessors'])-1)
            total_keys += _uint(doc['accessors'][input_index]['count'], 10000, 1)
            require(total_keys <= 2000000, 'MODEL_KEYS_BUDGET')
            times, values = accessor(doc, binary, sampler['input']), accessor(doc, binary, sampler['output'])
            dim = 4 if prop == 'rotation' else 3
            require(times.dtype.kind == values.dtype.kind == 'f' and times.shape[1] == 1 and values.shape == (len(times), dim)
                    and len(times) <= 10000 and np.isfinite(times).all() and np.isfinite(values).all()
                    and (times >= 0).all() and (times <= 3600).all() and (np.diff(times[:, 0]) > 0).all(), 'MODEL_ANIMATION_KEYS')
            if prop == 'rotation':
                require((np.linalg.norm(values, axis=1) > 1e-10).all(), 'MODEL_QUATERNION')
            channels.append(dict(node=ni, path=('translation', 'rotation', 'scale').index(prop),
                                 interpolation=int(method == 'LINEAR'), times=np.asarray(times[:, 0], '<f8'), values=np.asarray(values, '<f8')))
        require(0 < len(channels) <= 3*len(nodes), 'MODEL_ANIMATION_CHANNELS')
        clips.append(dict(name=animation.get('name', f'clip-{len(clips)}'), channels=channels,
                          duration=max(float(c['times'][-1]) for c in channels)))
    material = doc.get('materials', [])[ _uint(primitive.get('material'), len(doc.get('materials', []))-1)]
    require(material.get('doubleSided', False) is True and material.get('alphaMode', 'OPAQUE') == 'OPAQUE', 'MODEL_MATERIAL_SUBSET')
    metadata = dict(file=Path(path).name, sha256=entry['sha256'], bytes=entry['bytes'], vertices=len(xyz), triangles=len(faces),
                    nodes=len(nodes), joints=len(joints), influences_per_vertex=weights.shape[1],
                    maximum_nonzero_influences=int((weights > 0).sum(axis=1).max()) if weights.size else 0,
                    weight_sum_max_error=float(np.abs(weights.astype('f8').sum(axis=1)-1).max()) if weights.size else 0,
                    images=len(doc.get('images', [])), material='opaque-double-sided',
                    animations=[dict(name=c['name'], duration=c['duration'], channels=len(c['channels'])) for c in clips])
    return dict(positions=xyz, faces=faces, nodes=typed_nodes, joints=joints, inverse_bind=ibm,
                joint_data=joint_data, weights=weights, mesh_node=mesh_node, clips=clips, metadata=metadata)


def write_scene(path, instances, times, pixels=256, tile=32):
    require(1 <= len(instances) <= 12 and 1 <= len(times) <= 60, 'MODEL_SCENE_COUNT')
    _uint(pixels, 512, 2); _uint(tile, 64, 16)
    require(all(type(t) in (int, float) and np.isfinite(t) and 0 <= t <= 3600 for t in times), 'MODEL_FRAME_TIME')
    total_vertices = sum(len(x['asset']['positions']) for x in instances)
    total_faces = sum(len(x['asset']['faces']) for x in instances)
    require(total_vertices <= 6100000 and total_faces <= 8000000
            and ((pixels+tile-1)//tile)**2 * total_faces <= 536870912, 'MODEL_SCENE_BUDGET')
    with Path(path).open('wb') as out:
        out.write(b'AREMDL01'+struct.pack('<5I', len(instances), len(times), pixels, pixels, tile))
        out.write(np.asarray(times, '<f8').tobytes())
        for instance in instances:
            a = instance['asset']; clip = instance.get('clip')
            channels = [] if clip is None else a['clips'][_uint(clip, len(a['clips'])-1)]['channels']
            nv, nt, nn, nj = len(a['positions']), len(a['faces']), len(a['nodes']), len(a['joints'])
            out.write(struct.pack('<7I', nv, nt, nn, nj, a['weights'].shape[1], a['mesh_node'], len(channels)))
            matrix = np.asarray(instance.get('placement', np.eye(4)), '<f8')
            require(matrix.shape == (4, 4) and np.isfinite(matrix).all() and np.array_equal(matrix[3], [0, 0, 0, 1]), 'MODEL_PLACEMENT')
            color = instance.get('color', [185, 195, 215, 255])
            require(len(color) == 4 and all(type(c) is int and 0 <= c <= 255 for c in color), 'MODEL_COLOR')
            out.write(matrix.tobytes()); out.write(bytes(color))
            for node in a['nodes']:
                out.write(struct.pack('<iI', node['parent'], int('matrix' in node)))
                if 'matrix' in node:
                    out.write(np.asarray(node['matrix'], '<f8').tobytes())
                else:
                    out.write(np.concatenate([node['t'], node['q'], node['s']]).astype('<f8').tobytes())
            out.write(np.asarray(a['joints'], '<u4').tobytes()); out.write(a['inverse_bind'].astype('<f8').tobytes())
            for key, dtype in (('positions', '<f4'), ('faces', '<u4'), ('joint_data', '<u4'), ('weights', '<f4')):
                out.write(np.asarray(a[key], dtype).tobytes())
            for c in channels:
                out.write(struct.pack('<4I', c['node'], c['path'], c['interpolation'], len(c['times'])))
                out.write(c['times'].astype('<f8').tobytes()); out.write(c['values'].astype('<f8').tobytes())
    require(Path(path).stat().st_size <= 536870912, 'MODEL_INPUT_BYTES')
    return dict(protocol='are.model-input.v1', sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                bytes=Path(path).stat().st_size, vertices=total_vertices, triangles=total_faces, pixels=pixels, tile=tile,
                times=list(times), instances=[dict(source=x['asset']['metadata']['sha256'], clip=x.get('clip'),
                color=x.get('color', [185, 195, 215, 255]), placement=np.asarray(x.get('placement', np.eye(4))).tolist()) for x in instances])


def build_model_probe(directory):
    target = Path(directory).resolve(); target.mkdir(parents=True, exist_ok=True)
    sources = {n: (NATIVE/n).read_bytes() for n in SOURCES}
    for name, data in sources.items():
        (target/name).write_bytes(data)
    cxx = compiler(); flags = [*FLAGS, '-pthread']
    exe = target/('model_probe.exe' if sys.platform == 'win32' else 'model_probe')
    result = subprocess.run([cxx, *flags, str(target/'model_main.cpp'), '-o', str(exe)], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('MODEL_BUILD_FAILED:'+result.stderr[-6000:])
    receipt = dict(protocol='are.model-build.v1', source_sha256={k: hashlib.sha256(v).hexdigest() for k, v in sources.items()},
                   binary_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(), flags=flags, diagnostics=result.stderr,
                   compiler=subprocess.check_output([cxx, '--version'], text=True).splitlines()[0], python_in_runtime=False)
    return exe, receipt


def run_model(executable, request, workers=4, repeats=15, policy='combined', mode='render', timeout=600):
    from .bio_workrooms import POLICIES
    _uint(workers, 8, 1); _uint(repeats, 30, 1); _uint(timeout, 1800, 1)
    require(policy in POLICIES and mode in ('pose', 'render'), 'MODEL_RUN_POLICY')
    result = subprocess.run([str(executable), str(request), str(workers), str(repeats), policy, mode],
                            capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[-2000:])
    return decode_output(result.stdout, workers, repeats, policy, mode)


def decode_output(raw, workers, repeats, policy, mode='render'):
    """Validate the untrusted binary/JSON process boundary before exposing buffers."""
    if mode == 'pose':
        require(raw[:8] == b'AREPOSE1' and len(raw) >= 16, 'MODEL_POSE_PROTOCOL')
        nf, nm = struct.unpack_from('<2I', raw, 8); offset, frames = 16, []
        require(1 <= nf <= 60 and 1 <= nm <= 12, 'MODEL_POSE_SHAPE')
        for _ in range(nf):
            models = []
            for _ in range(nm):
                require(offset+4 <= len(raw), 'MODEL_POSE_TRUNCATED')
                n = struct.unpack_from('<I', raw, offset)[0]; offset += 4
                require(1 <= n <= 6100000 and offset+24*n <= len(raw), 'MODEL_POSE_TRUNCATED')
                models.append(np.frombuffer(raw, dtype='<f8', count=n*3, offset=offset).reshape(n, 3))
                offset += n*24
            frames.append(models)
        require(offset == len(raw) and all(np.isfinite(m).all() for f in frames for m in f), 'MODEL_POSE_OUTPUT')
        return dict(poses=frames, response_sha256=hashlib.sha256(raw).hexdigest())
    require(raw[:8] == b'AREMOUT1' and len(raw) >= 24, 'MODEL_OUTPUT_PROTOCOL')
    w, h, nf, nj = struct.unpack_from('<4I', raw, 8)
    require(2 <= w <= 512 and 2 <= h <= 512 and nf == repeats and 2 <= nj <= 131072
            and len(raw) == 24+nj+w*h*(4*nf+8), 'MODEL_OUTPUT_LENGTH')
    receipt = json.loads(raw[24:24+nj], object_pairs_hook=_object); start = 24+nj
    require(receipt.get('protocol') == 'are.model-probe.receipt.v1' and receipt.get('workers') == workers
            and receipt.get('policy') == policy and receipt.get('full_buffer_parity') is True
            and receipt.get('python_in_runtime') is False and receipt.get('warmups') == 3
            and receipt.get('hardware_gpu_submitted') is False
            and receipt.get('serial_reference_first_frame') is True, 'MODEL_OUTPUT_RECEIPT')
    for field, limit in [('triangles',8000000),('vertices',6100000),('models',12),('spatial_references',67108864)]:
        _uint(receipt.get(field),limit,0 if field == 'spatial_references' else 1)
    construction = receipt.get('construction_fit_and_serial_reference_ms')
    require(type(construction) in (int,float) and np.isfinite(construction) and construction >= 0, 'MODEL_OUTPUT_TIMING')
    writes = receipt.get('sample_writes')
    require(isinstance(writes,list) and len(writes) == repeats
            and all(type(x) is int and 0 <= x <= 4*w*h*receipt['triangles'] for x in writes), 'MODEL_OUTPUT_WRITES')
    for prefix in ('baseline_', 'candidate_'):
        for field in ('total_ms', 'geometry_ms', 'render_ms', 'cpu_ms'):
            values = receipt.get(prefix+field)
            require(isinstance(values,list) and len(values) == repeats
                    and all(type(x) in (int, float) and np.isfinite(x) and x >= 0 for x in values), 'MODEL_OUTPUT_TIMING')
    frames = np.frombuffer(raw, dtype='u1', count=w*h*nf*4, offset=start).reshape(nf, h, w, 4)
    resolved = np.frombuffer(raw, dtype='u1', count=w*h*4, offset=start+w*h*nf*4).reshape(h, w, 4)
    depth = np.frombuffer(raw, dtype='<f4', count=w*h, offset=start+w*h*(nf*4+4)).reshape(h, w)
    require(np.isfinite(depth).all(), 'MODEL_OUTPUT_DEPTH')
    receipt.update(response_sha256=hashlib.sha256(raw).hexdigest(), frame_sha256=[hashlib.sha256(f.tobytes()).hexdigest() for f in frames])
    return dict(receipt=receipt, frames=frames, resolved=resolved, depth=depth)
