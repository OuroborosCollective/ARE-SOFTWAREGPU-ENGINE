"""Real sparse negative files: a budget refusal is not source/geometry evidence."""
from contextlib import contextmanager, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from software_gpu import __version__
from software_gpu.integrations.aurion.offline_lod_worker import MAX_GLB_BYTES
from software_gpu.integrations.worldforge import main, review, scan
from software_gpu.tests.test_aurion_offline_lod import synthetic_glb


def make_job(root, *, name="a", oversized=True):
    """Create SHA-bound synthetic bytes, never a production asset claim."""
    job = root / "jobs" / (name * 64)
    job.mkdir(parents=True)
    model = job / "model.glb"
    model.write_bytes(synthetic_glb())
    if oversized:
        with model.open("r+b") as stream:
            stream.truncate(MAX_GLB_BYTES + 1)
    state = hashlib.sha256()
    with model.open("rb") as stream:
        for part in iter(lambda: stream.read(64 * 1024), b""):
            state.update(part)
    record = {"schema": "worldforge.blender-export.v1", "jobId": job.name,
              "files": [{"path": "model.glb", "size": model.stat().st_size,
                         "sha256": state.hexdigest()}]}
    (job / "receipt.json").write_text(json.dumps(record), encoding="utf-8")
    return job, record


@contextmanager
def forbid_source_open(model):
    """Observe IO only; all receipt/filesystem/renderer behavior stays real."""
    real_open = Path.open

    def observed_open(path, *args, **kwargs):
        if path == model:
            raise AssertionError("OVERBUDGET_SOURCE_WAS_OPENED")
        return real_open(path, *args, **kwargs)

    with patch.object(Path, "open", observed_open):
        yield


class WorldForgeBudgetTests(unittest.TestCase):
    def assert_budget_diagnostic(self, line, job):
        diagnostic = json.loads(line)
        self.assertEqual(diagnostic["schema"], "are.worldforge.admission.v1")
        self.assertEqual(diagnostic["jobId"], job.name)
        self.assertEqual(diagnostic["status"], "not-admitted")
        self.assertEqual(diagnostic["reason"], "GLB_REVIEW_SIZE_LIMIT")
        self.assertEqual(diagnostic["observedBytes"], MAX_GLB_BYTES + 1)
        self.assertEqual(diagnostic["maxReviewBytes"], MAX_GLB_BYTES)
        self.assertIs(diagnostic["sourceHashVerified"], False)
        self.assertIs(diagnostic["geometryReviewed"], False)
        self.assertIs(diagnostic["manualReviewRequired"], True)
        receipt_bytes = (job / "receipt.json").read_bytes()
        self.assertEqual(diagnostic["receiptSha256"], hashlib.sha256(receipt_bytes).hexdigest())
        self.assertEqual(diagnostic["declaredModelSha256"], json.loads(receipt_bytes)["files"][0]["sha256"])
        self.assertNotIn("modelSha256", diagnostic)
        return diagnostic

    def test_fresh_oversized_review_refuses_before_reading_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            job, _ = make_job(root)
            with forbid_source_open(job / "model.glb"):
                with self.assertRaisesRegex(ValueError, "GLB_REVIEW_SIZE_LIMIT"):
                    review(job, root / "out")
            self.assertEqual(list((root / "out").rglob("report.json")), [])

    def test_exact_byte_limit_keeps_hash_and_parser_validation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            job, record = make_job(root)
            model = job / "model.glb"
            with model.open("r+b") as stream:
                stream.truncate(MAX_GLB_BYTES)
            state = hashlib.sha256()
            with model.open("rb") as stream:
                for part in iter(lambda: stream.read(64 * 1024), b""):
                    state.update(part)
            record["files"][0].update(size=MAX_GLB_BYTES, sha256=state.hexdigest())
            (job / "receipt.json").write_text(json.dumps(record), encoding="utf-8")
            output = io.StringIO()
            # The real bytes match their receipt; the GLB header still declares
            # the original small fixture length, so normal parsing must reject.
            with redirect_stdout(output), self.assertRaisesRegex(ValueError, "GLB_HEADER_INVALID"):
                scan(root / "jobs", root / "out", limit=1)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(list((root / "out").rglob("report.json")), [])

    def test_repeat_scan_is_unverified_budget_refusal_without_cached_geometry(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            job, _ = make_job(root)
            for _ in range(2):
                output = io.StringIO()
                with forbid_source_open(job / "model.glb"), redirect_stdout(output):
                    scan(root / "jobs", root / "out", limit=1)
                self.assert_budget_diagnostic(output.getvalue().strip(), job)
            self.assertEqual(list((root / "out").rglob("report.json")), [])
            # Changing bytes without changing size must never become a
            # source-hash identity claim, even with the same old receipt.
            with (job / "model.glb").open("r+b") as stream:
                stream.write(b"changed!")
            output = io.StringIO()
            with forbid_source_open(job / "model.glb"), redirect_stdout(output):
                scan(root / "jobs", root / "out", limit=1)
            self.assert_budget_diagnostic(output.getvalue().strip(), job)

    def test_old_oversized_manual_report_is_not_reused_as_geometry_evidence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            job, record = make_job(root)
            receipt_sha = hashlib.sha256((job / "receipt.json").read_bytes()).hexdigest()
            cached = root / "out" / job.name / __version__ / receipt_sha
            cached.mkdir(parents=True)
            report = {"schema": "are.worldforge.geometry-review.v1",
                      "engineVersion": __version__, "jobId": job.name,
                      "receiptSha256": receipt_sha,
                      "modelSha256": record["files"][0]["sha256"],
                      "status": "manual-review", "reason": "GLB_REVIEW_SIZE_LIMIT"}
            report_path = cached / "report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            before = report_path.read_bytes()
            output = io.StringIO()
            with forbid_source_open(job / "model.glb"), redirect_stdout(output):
                scan(root / "jobs", root / "out", limit=1)
            self.assert_budget_diagnostic(output.getvalue().strip(), job)
            self.assertEqual(report_path.read_bytes(), before)

    def test_budget_refusal_does_not_consume_valid_job_limit(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            over, _ = make_job(root)
            good, _ = make_job(root, name="b", oversized=False)
            os.utime(over, ns=(2_000_000_000, 2_000_000_000))
            os.utime(good, ns=(1_000_000_000, 1_000_000_000))
            output = io.StringIO()
            with forbid_source_open(over / "model.glb"), redirect_stdout(output):
                scan(root / "jobs", root / "out", limit=1)
            lines = output.getvalue().splitlines()
            self.assertEqual(len(lines), 2)
            self.assert_budget_diagnostic(lines[0], over)
            result = Path(lines[1])
            self.assertEqual(json.loads((result / "report.json").read_text())["status"], "reviewed")
            self.assertEqual(len(list(result.glob("*.bmp"))), 6)

    def test_changed_to_bounded_source_revalidates_size_hash_and_geometry(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            job, record = make_job(root)
            with redirect_stdout(io.StringIO()):
                scan(root / "jobs", root / "out", limit=1)
            raw = synthetic_glb()
            (job / "model.glb").write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "SOURCE_SIZE_MISMATCH"):
                scan(root / "jobs", root / "out", limit=1)
            record["files"][0]["size"] = len(raw)
            (job / "receipt.json").write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SOURCE_SHA256_MISMATCH"):
                scan(root / "jobs", root / "out", limit=1)
            record["files"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
            (job / "receipt.json").write_text(json.dumps(record), encoding="utf-8")
            result = review(job, root / "out")
            self.assertEqual(json.loads((result / "report.json").read_text())["status"], "reviewed")
            self.assertEqual(len(list(result.glob("*.bmp"))), 6)

    def test_single_review_cli_reports_unverified_refusal_without_success_report(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            job, _ = make_job(root)
            output = io.StringIO()
            with forbid_source_open(job / "model.glb"), redirect_stdout(output):
                main(["review", str(job), str(root / "out")])
            self.assert_budget_diagnostic(output.getvalue().strip(), job)
            self.assertEqual(list((root / "out").rglob("report.json")), [])

    def test_missing_or_resized_oversized_source_remains_a_scan_failure(self):
        for state in ("missing", "resized"):
            with self.subTest(state=state), TemporaryDirectory() as tmp:
                root = Path(tmp)
                job, _ = make_job(root)
                model = job / "model.glb"
                if state == "missing":
                    model.unlink()
                    expected = "SOURCE_FILE_MISSING_OR_LINK"
                else:
                    with model.open("r+b") as stream:
                        stream.truncate(MAX_GLB_BYTES + 2)
                    expected = "SOURCE_SIZE_MISMATCH"
                output = io.StringIO()
                with redirect_stdout(output), self.assertRaisesRegex(ValueError, expected):
                    scan(root / "jobs", root / "out", limit=1)
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(list((root / "out").rglob("report.json")), [])

    @unittest.skipUnless(os.name == "posix", "real POSIX symlink fixture")
    def test_oversized_symlink_is_not_classified_as_budget_refusal(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            job, _ = make_job(root)
            model = job / "model.glb"
            target = root / "external.glb"
            model.rename(target)
            model.symlink_to(target)
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaisesRegex(ValueError, "SOURCE_FILE_MISSING_OR_LINK"):
                scan(root / "jobs", root / "out", limit=1)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(list((root / "out").rglob("report.json")), [])


if __name__ == "__main__":
    unittest.main()
