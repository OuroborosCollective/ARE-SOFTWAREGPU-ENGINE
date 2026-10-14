"""Fail-closed contract tests for the Hugging Face Jobs CPU runner (no paid calls)."""
import json
import subprocess
import sys
import tempfile
import io
import contextlib
import os
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import miha_huggi_jobs as jobs

SHA = 'a' * 40
CONFIG = {
    'code_revision': 'a' * 40,
    'base_model': 'Qwen/Qwen2.5-0.5B-Instruct',
    'base_revision': '7ae557604adf67be50417f59c2c2f167def9a775',
    'evidence_revision': 'b' * 40,
    'atomic_revision': 'c' * 40,
    'bench_revision': 'd' * 40,
}


class HuggiJobsContractTests(unittest.TestCase):
    def test_plan_is_pinned_cpu_only_no_credentials(self):
        p = jobs.build_plan(SHA, 'audit', 'cpu-upgrade', 2, CONFIG)
        self.assertEqual(p['image'], 'python:3.12')
        self.assertEqual(p['flavor'], 'cpu-upgrade')
        self.assertEqual(p['timeout'], '2h')
        self.assertEqual(p['command'][:2], ['python', '-c'])
        self.assertEqual(p['command'][3], SHA)
        self.assertNotIn('HF_TOKEN', json.dumps(p))
        self.assertEqual(p['device'], 'cpu')
        self.assertEqual(p['renderer_commit'], SHA)
        self.assertEqual(p['model_code_revision'], CONFIG['code_revision'])
        self.assertFalse(p['submitted'])
        self.assertFalse(p['training_completed'])
        self.assertFalse(p['release_accepted'])

    def test_train_job_requires_immutable_renderer(self):
        for ref in ['main', 'x'*39, '../etc/passwd', 'a'*41, 'g'*40]:
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                jobs.build_plan(ref, 'train', 'cpu-upgrade', 3, CONFIG)

    def test_only_authorized_cpu_base_and_pinned_datasets(self):
        for field, bad in [('base_model', 'deepseek-ai/DeepSeek-R1-Distill-Qwen-7B'),
                           ('base_revision', 'main'), ('code_revision', 'main'),
                           ('evidence_revision', ''), ('bench_revision', 'latest')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                jobs.build_plan(SHA, 'audit', 'cpu-upgrade', 1, {**CONFIG, field: bad})

    def test_disallow_gpu_and_unsafe_deadlines(self):
        for flavor in ['a10g-small', 't4-small', 'gpu', 'cpu-basic']:
            with self.subTest(flavor=flavor), self.assertRaises(ValueError):
                jobs.build_plan(SHA, 'train', flavor, 1, CONFIG)
        for hours in [0, -1, 25, 2.5, True]:
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                jobs.build_plan(SHA, 'train', 'cpu-upgrade', hours, CONFIG)

    def test_tight_budget_rejects_before_submission(self):
        p = jobs.build_plan(SHA, 'train', 'cpu-upgrade', 6, CONFIG)
        self.assertEqual(p['estimated_max_usd'], '0.18')
        with self.assertRaises(ValueError):
            jobs.check_budget(p, '0.17')
        self.assertEqual(jobs.check_budget(p, '0.20'), '0.20')
        for value in ['NaN', '-2', 'none', '0']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                jobs.check_budget(p, value)

    def test_confirm_and_token_required_before_paid_job(self):
        p = jobs.build_plan(SHA, 'train', 'cpu-upgrade', 1, CONFIG)
        for (confirmation, token) in [(False, 'valid'), (True, ''), (True, ' ')]:
            with self.subTest(confirmation=confirmation, token=token), self.assertRaises(ValueError):
                jobs.validate_submission(p, confirmation, token, '1.00')
        self.assertTrue(jobs.validate_submission(p, True, 'valid', '1.00'))

    def test_budget_uses_real_memory_threshold(self):
        with self.assertRaises(RuntimeError):
            jobs.require_training_memory(16_000_000_000)
        self.assertTrue(jobs.require_training_memory(32_000_000_000))

    def test_publish_gate_refuses_incomplete_and_non_cpu_adapter(self):
        good = {'training_completed': True, 'device': 'cpu',
                'optimizer_steps': 3, 'status': 'candidate_unvalidated', 'success': False}
        jobs.require_publishable(good)
        for diff in ({'training_completed': False}, {'device': 'cuda'},
                     {'optimizer_steps': 0}, {'status': 'evaluated_pass'},
                     {'success': True}):
            with self.subTest(diff=diff), self.assertRaises(ValueError):
                jobs.require_publishable({**good, **diff})

    def test_job_prefix_is_unique_and_restricted(self):
        self.assertEqual(jobs.candidate_prefix('f' * 24), 'huggi/jobs/' + 'f'*24)
        for ident in ['x'*24, '123', '../other', 'a'*25]:
            with self.subTest(ident=ident), self.assertRaises(ValueError):
                jobs.candidate_prefix(ident)

    def test_paid_submission_uses_provider_job_id_without_overriding_builtin(self):
        # The paid provider is the only replaced boundary; no request is sent.
        # Hugging Face injects JOB_ID as a built-in environment variable.
        calls = []
        def capture_job(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(id='f' * 24, url='https://huggingface.co/jobs/test/' + 'f' * 24)
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / 'training.json'
            config.write_text(json.dumps(CONFIG))
            stream = io.StringIO()
            fake_hub = SimpleNamespace(run_job=capture_job)
            with patch.dict(sys.modules, {'huggingface_hub': fake_hub}):
                with patch.dict(os.environ, {'HF_TOKEN': 'test-only-secret'}):
                    with contextlib.redirect_stdout(stream):
                        jobs.main(['submit', '--renderer-sha', SHA, '--mode', 'train',
                                   '--flavor', 'cpu-upgrade', '--timeout-hours', '2',
                                   '--max-usd', '0.10', '--confirm-paid-job',
                                   '--config', str(config)])
        self.assertEqual(len(calls), 1)
        self.assertNotIn('JOB_ID', calls[0]['env'])
        self.assertEqual(calls[0]['secrets'], {'HF_TOKEN': 'test-only-secret'})
        response = json.loads(stream.getvalue())
        self.assertEqual(response['job_id'], 'f' * 24)
        self.assertEqual(response['candidate_prefix'], 'huggi/jobs/' + 'f' * 24)
        self.assertFalse(response['training_completed'])

    def test_workflow_never_interpolates_dispatch_inputs_inside_shell(self):
        # Workflow-dispatch strings are attacker-controlled data and must be
        # passed as environment values rather than inlining into shell syntax.
        workflow = (ROOT / '.github/workflows/miha-huggi-jobs.yml').read_text()
        self.assertIn('MIHA_MAX_USD: ${{ inputs.max_usd }}', workflow)
        in_shell = False
        for line in workflow.splitlines():
            if line.strip() == 'run: |':
                in_shell = True
                continue
            if in_shell and line.strip() and not line.startswith('          '):
                in_shell = False
            if in_shell:
                self.assertNotIn('${{ inputs.', line)

    def test_worker_early_rejects_missing_credential(self):
        with tempfile.TemporaryDirectory() as td:
            env = {'PATH': '/usr/bin:/bin'}
            process = subprocess.run([sys.executable, str(ROOT/'scripts/miha_huggi_jobs.py'),
                                      'worker', '--renderer-sha', SHA, '--mode', 'train',
                                      '--output-dir', td], env=env, text=True, capture_output=True)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn('HF_TOKEN_REQUIRED', process.stderr)
            self.assertEqual(list(Path(td).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
