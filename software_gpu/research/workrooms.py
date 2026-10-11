"""Wolfram JSON/binary transport boundary. All render and scheduler loops are C++17."""
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys

from .native_symbolic import FLAGS, NATIVE, compiler

STAGES = [dict(kind=k, color=c) for k, c in
          zip(('render', 'raster', 'msaa', 'aa'), ('green', 'blue', 'orange', 'purple'))]


def descriptor(width=32, height=32, tile=8, frame=0):
    return dict(protocol='are.workrooms.v1', width=width, height=height,
                tile=tile, frame=frame, stages=[dict(s) for s in STAGES],
                coordinates=['slot_x', 'slot_y', 'operation', 'frame'])


def parse_descriptor(source):
    """Finite whitelist, not eval/ToExpression of incoming user code."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('ROOM_DUPLICATE_KEY')
            result[key] = value
        return result
    if not isinstance(source, str) or len(source) > 4096:
        raise ValueError('ROOM_DESCRIPTOR_BUDGET')
    obj = json.loads(source, object_pairs_hook=unique)
    if not isinstance(obj, dict) or set(obj) != set(descriptor()):
        raise ValueError('ROOM_DESCRIPTOR_SCHEMA')
    for key, lo, hi in [('width', 2, 1024), ('height', 2, 1024), ('tile', 1, 64), ('frame', 0, 1000000)]:
        if type(obj[key]) is not int or not lo <= obj[key] <= hi:
            raise ValueError('ROOM_DESCRIPTOR_BUDGET')
    if obj != descriptor(obj['width'], obj['height'], obj['tile'], obj['frame']):
        raise ValueError('ROOM_DESCRIPTOR_SCHEMA')
    return obj


def build_workrooms(directory):
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=True)
    sources = {name: (NATIVE/name).read_bytes() for name in
               ('core.hpp', 'workrooms.hpp', 'workrooms_wire.hpp', 'workrooms_main.cpp')}
    for name, data in sources.items():
        (target/name).write_bytes(data)
    cxx = compiler()
    flags = [*FLAGS, '-pthread']
    exe = target / ('workrooms.exe' if sys.platform == 'win32' else 'workrooms')
    result = subprocess.run([cxx, *flags, str(target/'workrooms_main.cpp'), '-o', str(exe)],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('ROOM_BUILD_FAILED:' + result.stderr[-6000:])
    receipt = dict(protocol='are.workrooms.build.v1', flags=flags,
                   compiler=subprocess.check_output([cxx, '--version'], text=True).splitlines()[0],
                   source_sha256={k: hashlib.sha256(v).hexdigest() for k, v in sources.items()},
                   binary_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                   python_in_runtime=False, diagnostics=result.stderr)
    (target/'build.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    return exe, receipt


def encode_request(ir, scene):
    """Scene = [{vertices: three clip-space xyzw, rgba: four bytes}]."""
    ir = parse_descriptor(json.dumps(ir))
    if not isinstance(scene, list) or not 1 <= len(scene) <= 64 or ir['width']*ir['height']*len(scene) > 67108864:
        raise ValueError('ROOM_SCENE_BUDGET')
    parts = [struct.pack('<5I', *(ir[k] for k in ('width', 'height', 'tile', 'frame')), len(scene))]
    for triangle in scene:
        if not isinstance(triangle, dict) or set(triangle) != {'vertices', 'rgba'}:
            raise ValueError('ROOM_TRIANGLE_SCHEMA')
        vertices, rgba = triangle['vertices'], triangle['rgba']
        if len(vertices) != 3 or any(len(v) != 4 for v in vertices) or len(rgba) != 4:
            raise ValueError('ROOM_TRIANGLE_SHAPE')
        if any(type(c) is not int or not 0 <= c <= 255 for c in rgba):
            raise ValueError('ROOM_RGBA')
        values = [v for vertex in vertices for v in vertex]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('ROOM_FINITE_GEOMETRY')
        try:
            parts.append(struct.pack('<12f4B', *values, *rgba))
        except (OverflowError, struct.error) as exc:
            raise ValueError('ROOM_FLOAT32') from exc
    payload = b''.join(parts)
    # Correlation tag only. Native echoes this value; it does not authenticate it.
    return b'ARERIN01' + hashlib.sha256(payload).digest() + payload


def decode_response(data, request):
    if len(data) < 52 or data[:8] != b'AREROUT1' or data[8:40] != request[8:40]:
        raise ValueError('ROOM_RESPONSE_PROTOCOL')
    width, height = struct.unpack_from('<2I', data, 40)
    if (width, height) != struct.unpack_from('<2I', request, 40):
        raise ValueError('ROOM_RESPONSE_SHAPE')
    size = width*height*4
    end = 48+3*size
    if len(data) < end+4:
        raise ValueError('ROOM_RESPONSE_TRUNCATED')
    length, = struct.unpack_from('<I', data, end)
    if length > 65536 or len(data) != end+4+length:
        raise ValueError('ROOM_RESPONSE_LENGTH')
    receipt = json.loads(data[end+4:])
    _, _, tile, frame, count = struct.unpack_from('<5I', request, 40)
    tiles = ((width+tile-1)//tile)*((height+tile-1)//tile)
    expected = [count, tiles, tiles, tiles]
    waves = receipt.get('waves', [])
    if (receipt.get('protocol') != 'are.workrooms.receipt.v1' or
            receipt.get('handoff_ready') is not True or receipt.get('worker_parity') is not True or
            receipt.get('python_in_runtime') is not False or receipt.get('hardware_gpu_submitted') is not False or
            receipt.get('rooms_executed') != sum(expected) or receipt.get('frame') != frame or
            receipt.get('tile') != tile or receipt.get('triangles') != count or len(waves) != 4):
        raise ValueError('ROOM_RESPONSE_RECEIPT')
    for i, wave in enumerate(waves):
        if ({k: wave.get(k) for k in ('kind', 'color')} != STAGES[i] or
                wave.get('executed') != expected[i] or
                len(wave.get('worker_jobs', [])) != receipt.get('workers') or
                sum(wave.get('worker_jobs', [])) != expected[i]):
            raise ValueError('ROOM_RESPONSE_INCOMPLETE')
    return dict(width=width, height=height, resolved=data[48:48+size],
                rgba=data[48+size:48+2*size], depth=data[48+2*size:end], receipt=receipt)


def run_workrooms(executable, ir, scene, workers=1, repeats=1):
    if type(workers) is not int or not 1 <= workers <= 8 or type(repeats) is not int or not 1 <= repeats <= 30:
        raise ValueError('ROOM_RUN_BUDGET')
    request = encode_request(ir, scene)
    result = subprocess.run([str(executable), str(workers), str(repeats)], input=request,
                            capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[-2000:])
    response = decode_response(result.stdout, request)
    response['receipt'].update(request_sha256=hashlib.sha256(request).hexdigest(),
                               response_sha256=hashlib.sha256(result.stdout).hexdigest(),
                               rgba_sha256=hashlib.sha256(response['rgba']).hexdigest())
    return response


def to_framebuffer(response):
    """Final CPU-buffer handoff into the existing engine, no Python rendering."""
    import numpy as np
    from software_gpu.graphics.framebuffer import Framebuffer
    width, height = response['width'], response['height']
    fb = Framebuffer(width, height)
    fb.color_buffer[...] = np.frombuffer(response['rgba'], dtype=np.uint8).reshape(height, width, 4)
    fb.depth_buffer[...] = np.frombuffer(response['depth'], dtype='<f4').reshape(height, width)
    return fb
