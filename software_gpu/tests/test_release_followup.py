"""Synthetic event metadata checks admission; live publication is separately verified."""
import copy
import unittest

from tools import release_gate

REPO = "OuroborosCollective/ARE-SOFTWAREGPU-ENGINE"
SHA = "a" * 40


def event():
    return {"repository": {"full_name": REPO}, "workflow_run": {
        "id": 91, "name": "Verified GoReleaser release",
        "path": ".github/workflows/goreleaser.yml", "event": "workflow_dispatch",
        "status": "completed", "conclusion": "success", "head_branch": "v1.2.50",
        "head_sha": SHA, "head_repository": {"full_name": REPO}}}


class ReleaseFollowupTests(unittest.TestCase):
    def test_successful_tag_candidate_keeps_exact_source_and_publisher_run(self):
        result = release_gate.parse_followup_event(event(), "workflow_run", REPO)
        self.assertEqual({"tag": "v1.2.50", "sha": SHA, "run_id": 91}, result)

    def test_green_branch_dispatch_pr_fork_wrong_workflow_and_bad_sha_are_not_releases(self):
        changes = (("head_branch", "main"), ("event", "pull_request"),
                   ("head_repository", {"full_name": "other/fork"}),
                   ("path", ".github/workflows/untrusted.yml"),
                   ("head_sha", "a" * 39), ("conclusion", "failure"), ("id", True))
        for key, value in changes:
            data = event(); data["workflow_run"][key] = value
            with self.subTest(key=key), self.assertRaises(release_gate.ReleaseGateError):
                release_gate.parse_followup_event(data, "workflow_run", REPO)

    def test_manual_retry_requires_strict_semver_and_owner_repository(self):
        data = {"repository": {"full_name": REPO}, "inputs": {"tag": "v1.2.50"}}
        self.assertEqual({"tag": "v1.2.50", "sha": None, "run_id": None},
                         release_gate.parse_followup_event(data, "workflow_dispatch", REPO))
        for tag in ("main", "v1.2.050", "v1.2.50-rc.1", "v1.2.50/evil"):
            with self.subTest(tag=tag), self.assertRaises(release_gate.ReleaseGateError):
                release_gate.parse_followup_event({**data, "inputs": {"tag": tag}}, "workflow_dispatch", REPO)
        with self.assertRaises(release_gate.ReleaseGateError):
            release_gate.parse_followup_event(data, "pull_request", REPO)

    def test_skipped_publish_job_cannot_be_successful_release_evidence(self):
        jobs = {"total_count": 3, "jobs": [
            {"id": i, "run_id": 91, "head_sha": SHA, "status": "completed", "conclusion": "success", "name": name}
            for i, name in enumerate(("Validate configuration, wheel and snapshot without publishing",
                "Publish only exact-main fully green CPU CI tag",
                "Publish PyPI on verified SemVer tag (Trusted Publishing)"), 1)]}
        release_gate.verify_followup_publisher_jobs(jobs, 91, SHA)
        for key, value in (("conclusion", "skipped"), ("head_sha", "b" * 40),
                           ("run_id", 92), ("name", "Different green job")):
            data = copy.deepcopy(jobs); data["jobs"][1][key] = value
            with self.subTest(key=key), self.assertRaises(release_gate.ReleaseGateError):
                release_gate.verify_followup_publisher_jobs(data, 91, SHA)


if __name__ == "__main__":
    unittest.main()
