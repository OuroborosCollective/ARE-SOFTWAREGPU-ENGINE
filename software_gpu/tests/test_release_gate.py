"""Fail-closed GoReleaser CI identity and artifact tests (stdlib only)."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

script = Path(__file__).resolve().parents[2] / 'tools/release_gate.py'
spec = importlib.util.spec_from_file_location('release_gate', script)
release_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_gate)

SHA = 'abcdef123456' * 3 + 'abcd'
REPO = 'OuroborosCollective/ARE-SOFTWAREGPU-ENGINE'


def run(run_id=91, conclusion='success', sha=SHA, event='push', branch='main', repo=REPO):
    return {'id': run_id, 'head_sha': sha, 'head_branch': branch,
            'event': event, 'status': 'completed', 'conclusion': conclusion,
            'head_repository': {'full_name': repo}}


def jobs(run_id=91, count=8, conclusion='success'):
    return {'total_count': count, 'jobs': [
        {'id': n, 'run_id': run_id, 'name': f'job{n}',
         'status': 'completed', 'conclusion': conclusion}
        for n in range(count)
    ]}


class ReleaseGateTest(unittest.TestCase):
    def test_selects_exact_successful_main_push(self):
        result = release_gate.select_run({'workflow_runs': [
            run(run_id=8, sha='0'*40), run(run_id=91)]}, SHA, REPO)
        self.assertEqual(91, result)
        self.assertEqual(8, release_gate.verify_jobs(jobs(), result))

    def test_does_not_use_old_green_after_newer_failed_run(self):
        with self.assertRaises(release_gate.ReleaseGateError):
            release_gate.select_run({'workflow_runs': [run(90), run(91, 'failure')]}, SHA, REPO)

    def test_rejects_fork_branch_and_dispatch(self):
        for override in ({'repo': 'stranger/fork'}, {'branch': 'feature'},
                         {'event': 'workflow_dispatch'}, {'sha': '0'*40}):
            with self.subTest(override=override):
                with self.assertRaises(release_gate.ReleaseGateError):
                    release_gate.select_run({'workflow_runs': [run(**override)]}, SHA, REPO)

    def test_requires_complete_eight_job_evidence(self):
        for bad in (jobs(count=7), {**jobs(), 'total_count': 9},
                    jobs(count=8, conclusion='skipped'), jobs(run_id=88)):
            with self.subTest(bad=bad):
                with self.assertRaises(release_gate.ReleaseGateError):
                    release_gate.verify_jobs(bad, 91)

    def test_requires_semver_tag_and_full_sha(self):
        for bad in ('gradio-android-abcdef', 'v1.2.0/evil', 'v01.2.0', '1.2.0'):
            with self.subTest(tag=bad), self.assertRaises(release_gate.ReleaseGateError):
                release_gate.validate_tag(bad)
        self.assertEqual('1.2.0-rc.2', release_gate.validate_tag('v1.2.0-rc.2'))
        with self.assertRaises(release_gate.ReleaseGateError):
            release_gate.select_run({'workflow_runs': [run()]}, '1234', REPO)

    def test_requires_version_matching_wheel_with_licence_and_notice(self):
        with tempfile.TemporaryDirectory() as folder:
            wheel = Path(folder) / 'software_gpu-1.2.0-py3-none-any.whl'
            with ZipFile(wheel, 'w') as z:
                z.writestr('software_gpu-1.2.0.dist-info/METADATA',
                           'Metadata-Version: 2.1\nName: software_gpu\nVersion: 1.2.0\n')
                z.writestr('software_gpu-1.2.0.dist-info/licenses/LICENSE.md', 'PolyForm Noncommercial')
                z.writestr('software_gpu-1.2.0.dist-info/licenses/NOTICE', 'Required Notice: Copyright ...')
            release_gate.verify_wheel(wheel, 'v1.2.0')
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_wheel(wheel, 'v1.2.1')
            with ZipFile(wheel, 'w') as z:
                z.writestr('software_gpu-1.2.0.dist-info/METADATA', 'Version: 1.2.0\n')
            with self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_wheel(wheel, 'v1.2.0')


if __name__ == '__main__':
    unittest.main()