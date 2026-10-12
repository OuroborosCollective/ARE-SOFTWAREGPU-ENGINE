"""Build/transport for the native bio-inspired ablation; no rendering in Python."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from .native_symbolic import FLAGS, NATIVE, compiler
from .workrooms import encode_request, decode_response

POLICIES = ('baseline', 'locality', 'reuse', 'frontier', 'checkpoints', 'combined',
            'without-locality', 'without-reuse', 'without-frontier', 'without-checkpoints')
BASELINE_COMMIT = '87ff610cd9419dd4b465e60bc19eb367a6b1a8f2'
BASELINE_SOURCE_SHA256 = '8645f2f2bc824107ecf9f7e80c155b84622f099c0aacb0c4870d580ba91b48ca'


def build_bio_workrooms(directory):
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=True)
    sources = {name: (NATIVE/name).read_bytes() for name in
               ('core.hpp', 'workrooms.hpp', 'workrooms_wire.hpp', 'bio_workrooms.hpp', 'bio_workrooms_main.cpp')}
    # A byte-exact historical test fixture also works in shallow CI checkouts.
    sources['frozen_workrooms.hpp'] = (NATIVE.parents[1]/'software_gpu/tests/fixtures/workrooms-baseline-87ff.hpp').read_bytes()
    if hashlib.sha256(sources['frozen_workrooms.hpp']).hexdigest() != BASELINE_SOURCE_SHA256:
        raise ValueError('ROOM_FROZEN_BASELINE_MISMATCH')
    # Reviewed PR #35 integration: shared validation extracted unchanged;
    # DirectEngine is additive. Existing room arithmetic is unchanged.
    # Historical receipts retain their original hashes; this build binds the new core.
    if hashlib.sha256(sources['core.hpp']).hexdigest() != '6728fedbef7f48f9db8e02d3ee082136c89f18ce83195b1bbcd1a4af348ac649':
        raise ValueError('ROOM_FROZEN_CORE_MISMATCH')
    for name, data in sources.items():
        (target/name).write_bytes(data)
    cxx = compiler()
    flags = [*FLAGS, '-pthread']
    exe = target/('bio_workrooms.exe' if sys.platform == 'win32' else 'bio_workrooms')
    result = subprocess.run([cxx, *flags, str(target/'bio_workrooms_main.cpp'), '-o', str(exe)],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('ROOM_BIO_BUILD_FAILED:' + result.stderr[-6000:])
    receipt = dict(protocol='are.bio-workrooms.build.v1', flags=flags,
                   compiler=subprocess.check_output([cxx, '--version'], text=True).splitlines()[0],
                   source_sha256={k: hashlib.sha256(v).hexdigest() for k, v in sources.items()},
                   binary_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                   baseline_commit=BASELINE_COMMIT, baseline_source_sha256=BASELINE_SOURCE_SHA256,
                   python_in_runtime=False, diagnostics=result.stderr)
    (target/'build.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    return exe, receipt


def validate_bio_receipt(receipt, policy, workers, repeats):
    if (receipt.get('policy') != policy or receipt.get('workers') != workers or
            receipt.get('baseline_workers') != workers or receipt.get('warmups') != 3 or
            receipt.get('paired_order') != 'alternating-baseline-first' or
            receipt.get('frontier_shared_stage_interval') is not
            (policy in ('frontier', 'combined', 'without-locality', 'without-reuse', 'without-checkpoints'))):
        raise ValueError('ROOM_BIO_RESPONSE_POLICY')
    for field in ('samples_ms', 'cpu_samples_ms', 'baseline_samples_ms', 'baseline_cpu_samples_ms'):
        values = receipt.get(field)
        if (not isinstance(values, list) or len(values) != repeats or
                any(type(v) not in (int, float) or not math.isfinite(v) or
                    v < 0 or (field in ('samples_ms', 'baseline_samples_ms') and v == 0) for v in values)):
            raise ValueError('ROOM_BIO_RESPONSE_TIMING')
    for field in ('baseline_construction_ms', 'candidate_construction_ms'):
        value = receipt.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('ROOM_BIO_RESPONSE_TIMING')
    refs = receipt.get('spatial_references')
    if type(refs) is not int or not 0 <= refs <= 67108864:
        raise ValueError('ROOM_BIO_RESPONSE_BINS')


def run_bio_workrooms(executable, ir, scene, workers=4, repeats=15, policy='combined'):
    if (type(workers) is not int or not 1 <= workers <= 8 or
            type(repeats) is not int or not 1 <= repeats <= 30 or
            type(policy) is not str or policy not in POLICIES):
        raise ValueError('ROOM_BIO_RUN_BUDGET')
    request = encode_request(ir, scene)
    result = subprocess.run([str(executable), str(workers), str(repeats), policy], input=request,
                            capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[-2000:])
    out = decode_response(result.stdout, request)
    validate_bio_receipt(out['receipt'], policy, workers, repeats)
    out['receipt'].update(request_sha256=hashlib.sha256(request).hexdigest(),
                          response_sha256=hashlib.sha256(result.stdout).hexdigest(),
                          rgba_sha256=hashlib.sha256(out['rgba']).hexdigest())
    return out
