"""Offline C++17 code generation/build tooling, never part of the native loop."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time

from .symbolic_wave import plan_ir

FLAGS = ('-std=c++17', '-O3', '-fno-fast-math', '-ffp-contract=off', '-Wall', '-Wextra')
NATIVE = Path(__file__).resolve().parents[2] / 'native' / 'symbolic'


def compiler():
    """Only a single discovered executable; no shell or caller-supplied flags."""
    for name in ('g++', 'clang++', 'c++'):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError('NATIVE_CPP_COMPILER_REQUIRED')


def emit_cpp(ir):
    plan = plan_ir(ir)
    by_id = plan.node_map()
    order = list(plan.inputs) + [name for wave in plan.waves for region in wave for name in region]
    ids = {name: i for i, name in enumerate(order)}
    inputs = {name: i for i, name in enumerate(plan.inputs)}
    outputs = {name: i for i, name in enumerate(plan.outputs)}
    lines = ['// Generated from validated ordered-f32-v1 IR. No algebraic rewrites.',
             '#pragma once', '#include "core.hpp"',
             'ARE_NOINLINE inline bool generated_fused(const float* const* in, float* const* out) {',
             '    std::uint32_t invalid = 0;']
    groups = {}
    for name in order:
        groups.setdefault(by_id[name].shape, []).append(name)
    for shape, names in groups.items():
        lines.append(f'    for (std::size_t k=0; k<{math.prod(shape)}; ++k) {{')
        for name in names:
            n = by_id[name]
            if n.op == 'input':
                expr = f'in[{inputs[name]}][k]'
            else:
                symbol = {'add': '+', 'sub': '-', 'mul': '*'}[n.op]
                expr = f'v{ids[n.deps[0]]} {symbol} v{ids[n.deps[1]]}'
            lines.append(f'        const float v{ids[name]} = {expr};')
            if n.op != 'input':
                lines.append(f'        invalid |= are::nonfinite(v{ids[name]});')
            if name in outputs:
                lines.append(f'        out[{outputs[name]}][k] = v{ids[name]};')
        lines.append('    }')
    lines += ['    return invalid == 0;', '}', 'inline const are::Graph generated_graph{', '    {']
    for name in order:
        n = by_id[name]
        a, b = [ids[x] for x in n.deps] if n.deps else (0, 0)
        lines.append(f'        {{are::Op::{n.op}, {a}, {b}, {math.prod(n.shape)}}},')
    lines += ['    },', '    {' + ','.join(str(ids[x]) for x in plan.inputs) + '},',
              '    {' + ','.join(str(ids[x]) for x in plan.outputs) + '},',
              f'    generated_fused, "{plan.sha256}"', '};', '']
    return '\n'.join(lines)


def build_native(ir, directory):
    """Emit exact sources, compile once, bind artifact/source hashes in receipt."""
    plan = plan_ir(ir)
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=True)
    sources = {'generated.hpp': emit_cpp(ir).encode(),
               **{name: (NATIVE/name).read_bytes() for name in ('core.hpp', 'main.cpp')}}
    for name, content in sources.items():
        (target/name).write_bytes(content)
    cxx = compiler()
    executable = target / ('kernel.exe' if sys.platform == 'win32' else 'kernel')
    command = [cxx, *FLAGS, str(target/'main.cpp'), '-o', str(executable)]
    start = time.perf_counter_ns()
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('NATIVE_CPP_BUILD_FAILED:' + result.stderr[-6000:])
    receipt = {'protocol': 'are.native-build.v1', 'graph_sha256': plan.sha256,
               'compiler': cxx, 'compiler_version': subprocess.check_output([cxx,'--version'],text=True).splitlines()[0],
               'flags': list(FLAGS), 'compile_ms': (time.perf_counter_ns()-start)/1e6,
               'source_sha256': {k:hashlib.sha256(v).hexdigest() for k,v in sources.items()},
               'binary_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
               'compiler_diagnostics': result.stderr,
               'python_in_runtime': False, 'workers': 1}
    (target/'build.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return executable, receipt


def encode_frames(ir, frames):
    """Test/build boundary: flatten binary32 in declared input order, LE wire."""
    import numpy as np
    from .symbolic_wave import _inputs
    plan = plan_ir(ir)
    cells = sum(math.prod(plan.node_map()[name].shape) for name in plan.inputs)
    if not 1 <= len(frames) <= 32 or cells*len(frames) > 8388608:
        raise ValueError('NATIVE_FRAME_BUDGET')
    parts = [b'AREF32V1', struct.pack('<II',len(frames),cells), bytes.fromhex(plan.sha256)]
    for frame in frames:
        _inputs(plan,frame)
        parts.extend(np.asarray(frame[name],dtype='<f4').tobytes(order='C') for name in plan.inputs)
    return b''.join(parts)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ir',required=True)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    ir=json.loads(Path(args.ir).read_text(encoding='utf-8'))
    executable,receipt=build_native(ir,args.output_dir)
    print(json.dumps({'executable':str(executable),'receipt':receipt}))


if __name__ == '__main__':
    main()
