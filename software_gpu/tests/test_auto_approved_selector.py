"""Dynamic MIHA Auto: real file contract for training only on approved Atomic SHA.

A moving live Evidence head does not invalidate the latest *approved* immutable
train set. Nor does the existence of a later Atomic head authorize training it.
No provider fakes, model weights, or reported speedup numbers in these tests.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from software_gpu.training.auto_incremental import (
    approve_training_snapshot, inspect_release
)


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def approved_release(folder):
    root = Path(folder)
    (root / "data").mkdir(parents=True)
    row = {
        "id": "record-example-one", "origin_record_id": "record-1",
        "task_type": "node",
        "input_json": json.dumps({"topic": "research", "sources": []}),
        "target_json": json.dumps({"status": "unverified", "claims": [],
                                  "used_sources": [], "missing_evidence": [],
                                  "next_paths": []}),
    }
    data = encoded(row) + b"\n"
    (root / "data/train.jsonl").write_bytes(data)
    manifest = {
        "builder_version": "2.1",
        "source_dataset": "Thorsu/miha-evidence",
        "builder_code_sha256": "a"*64,
        "dataset_revision": "b"*40,
        "benchmark_dataset": "Thorsu/miha-bench",
        "benchmark_revision": "c"*40,
        "records": {"record-1": "d"*64},
        "training_example_ids": ["record-example-one"],
        "examples": 1,
        "overlap": {"overlap": 0},
        "contains_hidden_chain_of_thought": False,
        "output_contract": "miha-five-key-v1",
        "train_jsonl_sha256": hashlib.sha256(data).hexdigest(),
    }
    (root / "build_manifest.json").write_bytes(encoded(manifest)+b"\n")
    return inspect_release(root)


def config():
    return {
        "code_revision": "e"*40,
        "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
        "base_revision": "f"*40,
        "evidence_revision": "b"*40,
        "atomic_revision": "1"*40,
        "bench_revision": "c"*40,
    }


class ApprovedSnapshotSelection(unittest.TestCase):
    def test_live_head_growing_does_not_unapprove_valid_frozen_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            release = approved_release(folder)
            original = config()
            output = approve_training_snapshot(
                original, release, atomic_sha="1"*40,
                live_evidence_sha="2"*40
            )
            self.assertEqual(output["training_config"]["evidence_revision"], "b"*40)
            self.assertEqual(output["training_config"]["atomic_revision"], "1"*40)
            self.assertEqual(output["live_evidence_sha"], "2"*40)
            self.assertEqual(output["status"], "AUDIT_REQUIRED")
            self.assertEqual(output["freshness"], "APPROVED_PINNED_BEHIND_LIVE")
            self.assertFalse(output["training_started"])
            self.assertFalse(output["release_accepted"])
            self.assertEqual(original, config())

    def test_same_live_revision_is_current_but_still_requires_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            release = approved_release(folder)
            output = approve_training_snapshot(
                config(), release, atomic_sha="1"*40, live_evidence_sha="b"*40
            )
            self.assertEqual(output["freshness"], "APPROVED_PINNED_CURRENT")
            self.assertEqual(output["status"], "AUDIT_REQUIRED")
            self.assertFalse(output["training_started"])

    def test_new_unreviewed_atomic_head_is_not_automatically_authorized(self):
        with tempfile.TemporaryDirectory() as folder:
            release = approved_release(folder)
            for unapproved in ("2"*40, "main", ""):
                with self.subTest(unapproved=unapproved):
                    with self.assertRaisesRegex(ValueError, "AUTO_DYNAMIC_APPROVAL_MISSING"):
                        approve_training_snapshot(config(), release,
                            atomic_sha=unapproved, live_evidence_sha="b"*40)
            for bad_live in ("main", "", None):
                with self.subTest(bad_live=bad_live):
                    with self.assertRaisesRegex(ValueError, "AUTO_DYNAMIC"):
                        approve_training_snapshot(config(), release,
                            atomic_sha="1"*40, live_evidence_sha=bad_live)

    def test_corrupt_atomic_manifest_cannot_hide_behind_successful_live_head(self):
        with tempfile.TemporaryDirectory() as folder:
            release = approved_release(folder)
            modified = dict(release)
            modified["sha256"] = "0"*64
            with self.assertRaisesRegex(ValueError, "AUTO_DYNAMIC"):
                approve_training_snapshot(config(), modified,
                    atomic_sha="1"*40, live_evidence_sha="b"*40)
            modified = dict(release)
            modified["manifest"] = dict(release["manifest"], benchmark_revision="0"*40)
            with self.assertRaisesRegex(ValueError, "AUTO_DYNAMIC"):
                approve_training_snapshot(config(), modified,
                    atomic_sha="1"*40, live_evidence_sha="b"*40)

    def test_approved_revision_must_be_audit_config_pin(self):
        with tempfile.TemporaryDirectory() as folder:
            release = approved_release(folder)
            modified = dict(config(), atomic_revision="2"*40)
            with self.assertRaisesRegex(ValueError, "AUTO_DYNAMIC_APPROVAL_MISSING"):
                approve_training_snapshot(modified, release,
                    atomic_sha="1"*40, live_evidence_sha="b"*40)


if __name__ == "__main__":
    unittest.main()
