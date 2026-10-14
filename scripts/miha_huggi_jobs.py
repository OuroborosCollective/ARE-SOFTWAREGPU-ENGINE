#!/usr/bin/env python3
"""Opt-in Hugging Face Jobs runner for immutable MIHA CPU-LoRA + SoftwareGPU.

This is a paid JOB launcher, not a GPU backend. The checkout is always an
immutable GitHub commit; training remains PyTorch CPU and SoftwareGPU only
renders observed metrics. `plan` performs no network or paid operations.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen

REPO = 'OuroborosCollective/ARE-SOFTWAREGPU-ENGINE'
MODEL_REPO = 'Thorsu/miha-deepseek-r1-distill-qwen-7b-lora'
BASE_MODEL = 'Qwen/Qwen2.5-0.5B-Instruct'
BASE_REVISION = '7ae557604adf67be50417f59c2c2f167def9a775'
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
JOB_ID = re.compile(r'[0-9a-f]{24}\Z')
# Public HF Jobs rates verified 2026-10-14. They are estimates, not billing API locks.
# CPU Basic (16 GB decimal) cannot meet the project's >=16 GiB RAM gate.
CPU_USD_PER_HOUR = {
    'cpu-upgrade': Decimal('0.03'),
    'cpu-xl': Decimal('1.00'),
    'cpu-performance': Decimal('1.90'),
}

# Python in the remote container downloads this *same file* from the immutable
# GitHub commit. No mutable `main`, no ad-hoc shell, no encoded bearer tokens.
BOOTSTRAP = (
    'import pathlib,runpy,sys,tempfile,urllib.request\n'
    'sha,mode=sys.argv[1:3]\n'
    'url=f"https://raw.githubusercontent.com/OuroborosCollective/'
    'ARE-SOFTWAREGPU-ENGINE/{sha}/scripts/miha_huggi_jobs.py"\n'
    'dst=pathlib.Path(tempfile.mkdtemp(prefix="miha-huggi-bootstrap-"))/'
    '"miha_huggi_jobs.py"\n'
    'with urllib.request.urlopen(url,timeout=60) as response:'
    ' dst.write_bytes(response.read())\n'
    'sys.argv=[str(dst),"worker","--renderer-sha",sha,"--mode",mode]\n'
    'runpy.run_path(str(dst),run_name="__main__")\n'
)


def require_sha(value: str, field: str) -> str:
    if not isinstance(value, str) or not HEX40.fullmatch(value):
        raise ValueError(f'PIN_REQUIRED: immutable 40-hex {field}')
    return value


def validate_config(settings: dict) -> None:
    if not isinstance(settings, dict):
        raise ValueError('INVALID_CONFIG: expected object')
    for name in ('code_revision', 'evidence_revision', 'atomic_revision',
                 'bench_revision', 'base_revision'):
        require_sha(settings.get(name), name)
    if (settings.get('base_model'), settings['base_revision']) != (BASE_MODEL, BASE_REVISION):
        raise ValueError('CPU_ONLY: unapproved base model or revision')


def build_plan(renderer_sha: str, mode: str, flavor: str,
               timeout_hours: int, settings: dict) -> dict:
    require_sha(renderer_sha, 'renderer_sha')
    validate_config(settings)
    if mode not in ('audit', 'train'):
        raise ValueError('UNSUPPORTED_MODE: audit or train required')
    if flavor not in CPU_USD_PER_HOUR:
        raise ValueError('CPU_ONLY: CPU profile with >=16 GiB required')
    if type(timeout_hours) is not int or not 1 <= timeout_hours <= 24:
        raise ValueError('TIMEOUT: whole hours in [1,24] required')
    estimate = CPU_USD_PER_HOUR[flavor] * timeout_hours
    return {
        'name': f'miha-{mode}-{renderer_sha[:10]}',
        'image': 'python:3.12',
        'command': ['python', '-c', BOOTSTRAP, renderer_sha, mode],
        'flavor': flavor, 'timeout': f'{timeout_hours}h',
        'env': {'CUDA_VISIBLE_DEVICES': '', 'HIP_VISIBLE_DEVICES': '',
                'ROCR_VISIBLE_DEVICES': '', 'TOKENIZERS_PARALLELISM': 'false',
                'HF_HUB_DISABLE_XET': '1', 'OMP_NUM_THREADS': '4',
                'MKL_NUM_THREADS': '4'},
        'device': 'cpu', 'renderer_commit': renderer_sha,
        'model_code_revision': settings['code_revision'],
        'evidence_revision': settings['evidence_revision'],
        'atomic_revision': settings['atomic_revision'],
        'holdout_revision': settings['bench_revision'],
        'estimated_max_usd': str(estimate.quantize(Decimal('0.01'))),
        'estimate_note': 'Published USD rate * time cap; actual provider billing may change',
        'submitted': False, 'training_completed': False, 'release_accepted': False,
    }


def check_budget(plan: dict, max_usd: str) -> str:
    try:
        limit = Decimal(max_usd)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('BUDGET: positive USD decimal required') from None
    if not limit.is_finite() or limit <= 0:
        raise ValueError('BUDGET: finite positive USD required')
    if Decimal(plan['estimated_max_usd']) > limit:
        raise ValueError('BUDGET: estimated hardware charge exceeds explicit budget')
    return str(limit)


def validate_submission(plan: dict, confirmed: bool, token: str, max_usd: str) -> bool:
    check_budget(plan, max_usd)
    if confirmed is not True:
        raise ValueError('PAID_JOB_CONFIRMATION_REQUIRED')
    if not isinstance(token, str) or not token.strip():
        raise ValueError('HF_TOKEN_REQUIRED: provide token via environment or GitHub secret')
    return True


def require_training_memory(available_bytes: int) -> bool:
    if available_bytes < 16 * 1024 ** 3:
        raise RuntimeError('CPU_ONLY: actual RAM <16 GiB; no training or truncation')
    return True


def candidate_prefix(job_id: str) -> str:
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise ValueError('INVALID_JOB_ID: Hugging Face 24-hex job id required')
    return f'huggi/jobs/{job_id}'


def require_publishable(receipt: dict) -> bool:
    if not isinstance(receipt, dict) or not (
        receipt.get('training_completed') is True and
        receipt.get('device') == 'cpu' and
        type(receipt.get('optimizer_steps')) is int and
        receipt['optimizer_steps'] > 0 and
        receipt.get('success') is False and
        receipt.get('status') == 'candidate_unvalidated'
    ):
        raise ValueError('CANDIDATE_BLOCKED: no completed CPU-only adapter receipt')
    return True


def run_command(argv: list[str], cwd: Path, environment: dict | None = None) -> None:
    # No shell expansion: command args are explicit, and no token enters argv.
    print(json.dumps({'event': 'exec', 'program': argv[:4], 'cwd': str(cwd)}), flush=True)
    subprocess.run(argv, cwd=str(cwd), env=environment, check=True)


def get_repo_snapshot(renderer_sha: str, destination: Path) -> Path:
    require_sha(renderer_sha, 'renderer_sha')
    uri = f'https://codeload.github.com/{REPO}/tar.gz/{renderer_sha}'
    archive = destination / 'renderer.tar.gz'
    with urlopen(uri, timeout=120) as response, archive.open('wb') as target:
        import shutil
        shutil.copyfileobj(response, target)
    with tarfile.open(archive, 'r:gz') as tar:
        tar.extractall(destination, filter='data')
    roots = [d for d in destination.iterdir() if d.is_dir()]
    if len(roots) != 1 or not (roots[0] / 'fixtures/miha/training.json').is_file():
        raise RuntimeError('PIN_MISMATCH: invalid renderer commit archive')
    if hashlib.sha256((roots[0] / 'scripts/miha_huggi_jobs.py').read_bytes()).digest() != hashlib.sha256(Path(__file__).read_bytes()).digest():
        raise RuntimeError('PIN_MISMATCH: bootstrap and immutable archive disagree')
    return roots[0]


def publish_candidate(output: Path, job_id: str, settings: dict) -> dict:
    """Write *only* completed, unvalidated adapters to immutable job prefixes."""
    from huggingface_hub import HfApi, CommitOperationAdd, hf_hub_download
    prefix = candidate_prefix(job_id)
    adapter = output / 'candidate' / 'adapter'
    receipt = json.loads((adapter / 'training_manifest.json').read_text())
    require_publishable(receipt)
    if receipt.get('code_revision') != settings['code_revision']:
        raise ValueError('CANDIDATE_BLOCKED: training code revision differs')
    if receipt.get('base_model_revision') != settings['base_revision']:
        raise ValueError('CANDIDATE_BLOCKED: base revision differs')
    api = HfApi()
    if api.whoami().get('name') != 'Thorsu':
        raise ValueError('WRONG_ACCOUNT: only Thorsu may publish candidates')
    head = api.model_info(MODEL_REPO).sha
    if any(file.startswith(prefix + '/') for file in api.list_repo_files(MODEL_REPO, revision=head)):
        raise ValueError('IMMUTABLE_TARGET: candidate prefix already populated')
    paths = sorted(p for p in adapter.rglob('*') if p.is_file())
    if not paths or not (adapter / 'adapter_model.safetensors').is_file():
        raise ValueError('CANDIDATE_BLOCKED: adapter files missing')
    operation = [CommitOperationAdd(path_in_repo=prefix + '/' + p.relative_to(adapter).as_posix(),
                                    path_or_fileobj=str(p)) for p in paths]
    commit = api.create_commit(repo_id=MODEL_REPO, parent_commit=head,
                               commit_message='Huggi CPU-LoRA candidate; holdout pending',
                               operations=operation)
    for p in paths:
        remote = Path(hf_hub_download(repo_id=MODEL_REPO,
                         filename=prefix + '/' + p.relative_to(adapter).as_posix(),
                         revision=commit.oid, force_download=True))
        if hashlib.sha256(remote.read_bytes()).digest() != hashlib.sha256(p.read_bytes()).digest():
            raise RuntimeError('HUB_READBACK_FAILED: published adapter digest differs')
    record = {'candidate_revision': commit.oid, 'candidate_prefix': prefix,
              'files_verified': len(paths), 'hub_readback': True,
              'status': 'benchmark_required', 'success': False}
    (output / 'publication.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record), flush=True)
    return record


def worker(renderer_sha: str, mode: str, output_dir: str) -> None:
    require_sha(renderer_sha, 'renderer_sha')
    if mode not in ('audit', 'train'):
        raise ValueError('UNSUPPORTED_MODE')
    # Exit before filesystem, downloads or provider charges for missing publication access.
    if mode == 'train' and not os.environ.get('HF_TOKEN', '').strip():
        raise SystemExit('HF_TOKEN_REQUIRED: train requires immutable candidate readback')
    if mode == 'train':
        candidate_prefix(os.environ.get('JOB_ID', ''))
    if os.environ.get('ACCELERATOR', 'none').lower() not in ('none', '', 'cpu', 'cpu-basic', 'cpu-upgrade'):
        raise ValueError('CPU_ONLY: accelerator not allowed')
    for item in ('CUDA_VISIBLE_DEVICES', 'HIP_VISIBLE_DEVICES', 'ROCR_VISIBLE_DEVICES'):
        os.environ[item] = ''
    with tempfile.TemporaryDirectory(prefix='miha-huggi-git-') as temporary:
        root = get_repo_snapshot(renderer_sha, Path(temporary))
        settings = json.loads((root / 'fixtures/miha/training.json').read_text())
        validate_config(settings)
        output = Path(output_dir).resolve()
        output.mkdir(parents=True, exist_ok=False)
        # The preflight loads the exact pinned CPU policy and tests actual RAM.
        run_command([sys.executable, '-u', 'scripts/miha_cpu_runner.py',
                     'preflight', '--output', str(output)], root)
        run_command([sys.executable, '-m', 'pip', 'install',
                     'huggingface_hub==0.35.3', '-e', '.'], root)
        run_command([sys.executable, '-m', 'unittest',
                     'software_gpu.tests.test_training_metrics', '-v'], root)
        run_command([sys.executable, '-u', 'scripts/miha_cpu_runner.py',
                     'audit', '--output', str(output)], root)
        if mode == 'audit':
            print(json.dumps({'status': 'AUDIT_PASS', 'training_completed': False,
                              'renderer_commit': renderer_sha, 'release_accepted': False}), flush=True)
            return
        from huggingface_hub import HfApi, hf_hub_download, snapshot_download
        if HfApi().whoami().get('name') != 'Thorsu':
            raise ValueError('WRONG_ACCOUNT: authorized Thorsu job required')
        req = hf_hub_download(repo_id=MODEL_REPO, filename='requirements-cpu.txt',
                              revision=settings['code_revision'])
        run_command([sys.executable, '-m', 'pip', 'install', '-r', req, '-e', '.'], root)
        run_command([sys.executable, '-u', 'scripts/miha_cpu_runner.py', 'train',
                     '--output', str(output), '--renderer-revision', renderer_sha], root)
        candidate = publish_candidate(output, os.environ['JOB_ID'], settings)
        snapshot = snapshot_download(MODEL_REPO, revision=settings['code_revision'],
                                     allow_patterns=['*.py', 'COMPUTE_POLICY.json'])
        env = {**os.environ, 'PYTHONPATH': snapshot}
        print(json.dumps({'status': 'BENCHMARK_START', 'candidate': candidate['candidate_revision']}), flush=True)
        run_command([sys.executable, '-u', str(Path(snapshot) / 'evaluate_v2.py'),
                     '--candidate-revision', candidate['candidate_revision'],
                     '--candidate-prefix', candidate['candidate_prefix'],
                     '--bench-revision', settings['bench_revision'],
                     '--code-revision', settings['code_revision'],
                     '--output-prefix', candidate['candidate_prefix'] + '/evaluation'], root, env)
        print(json.dumps({'status': 'BENCHMARK_EVALUATOR_EXIT_0',
                          'note': 'See evaluator holdout receipt and Hub readback for quality acceptance'}), flush=True)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description='Huggi CPU-only MIHA training with SoftwareGPU receipts')
    p.add_argument('action', choices=['plan', 'submit', 'worker'])
    p.add_argument('--renderer-sha', required=True)
    p.add_argument('--mode', choices=['audit', 'train'], default='audit')
    p.add_argument('--flavor', default='cpu-upgrade', choices=sorted(CPU_USD_PER_HOUR))
    p.add_argument('--timeout-hours', type=int, default=6)
    p.add_argument('--config', default='fixtures/miha/training.json')
    p.add_argument('--max-usd')
    p.add_argument('--confirm-paid-job', action='store_true')
    p.add_argument('--output-dir', default='/tmp/miha-huggi-output')
    args = p.parse_args(argv)
    if args.action == 'worker':
        worker(args.renderer_sha, args.mode, args.output_dir)
        return
    settings = json.loads(Path(args.config).read_text())
    plan = build_plan(args.renderer_sha, args.mode, args.flavor,
                      args.timeout_hours, settings)
    if args.action == 'plan':
        print(json.dumps(plan, sort_keys=True, indent=2))
        return
    token = os.environ.get('HF_TOKEN', '')
    validate_submission(plan, args.confirm_paid_job, token, args.max_usd)
    from huggingface_hub import run_job
    # Submission only: a job is not a completed training/benchmark.
    # JOB_ID belongs to the provider. Never override its built-in value:
    # the worker and this receipt must use the same immutable provider ID.
    launched = run_job(image=plan['image'], command=plan['command'],
                       flavor=plan['flavor'], timeout=plan['timeout'],
                       name=plan['name'], env=plan['env'],
                       secrets={'HF_TOKEN': token})
    print(json.dumps({'submitted': True, 'job_id': launched.id, 'job_url': launched.url,
                      'candidate_prefix': candidate_prefix(launched.id),
                      'renderer_commit': args.renderer_sha,
                      'estimated_max_usd': plan['estimated_max_usd'],
                      'training_completed': False, 'release_accepted': False}), flush=True)


if __name__ == '__main__':
    main()
