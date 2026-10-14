"""Fail-closed readiness rules for live MIHA Auto versus immutable Atomic SFT.

Tests create actual on-disk canonical files: none of the assertions relies
on fabricated benchmark scores or claims that viewer projections are SFT rows.
"""
import json
from pathlib import Path
import tempfile
import unittest

from software_gpu.training.auto_readiness import inventory, compare, pinned_sha


class TestMIHAAutoReadiness(unittest.TestCase):
    def make_tree(self, root, ids, *, missing_projection=False):
        canonical = Path(root) / "data" / "auto"
        projection = Path(root) / "data" / "auto_rows"
        canonical.mkdir(parents=True)
        projection.mkdir(parents=True)
        for index, name in enumerate(ids):
            (canonical / (name + ".json")).write_text(json.dumps({"record_id": name}))
            if not missing_projection or index != 0:
                (projection / (name + ".jsonl")).write_text(json.dumps({"id": name}) + "\n")

    def test_exact_pinned_and_current_auto_inventory_is_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_tree(folder, ["evidence-a", "evidence-b"])
            rec = inventory(folder)
            self.assertEqual(rec["canonical_records"], 2)
            self.assertEqual(rec["viewer_projection_rows"], 2)
            self.assertEqual(compare("a"*40, "a"*40, rec, rec)["status"], "PINNED_CURRENT")
            self.assertFalse(compare("a"*40, "a"*40, rec, rec)["training_started"])

    def test_updated_auto_requires_new_pinned_atomic_build(self):
        with tempfile.TemporaryDirectory() as p, tempfile.TemporaryDirectory() as c:
            self.make_tree(p, ["a", "b"])
            self.make_tree(c, ["a", "b", "c"])
            status = compare("a"*40, "b"*40, inventory(p), inventory(c))
            self.assertEqual(status["status"], "AUTO_REFRESH_REQUIRED")
            self.assertEqual(status["added_ids"], ["c"])
            self.assertEqual(status["pinned_canonical_records"], 2)
            self.assertEqual(status["current_canonical_records"], 3)
            self.assertFalse(status["training_started"])
            self.assertFalse(status["release_accepted"])

    def test_same_row_counts_but_different_source_revisions_also_block(self):
        with tempfile.TemporaryDirectory() as p, tempfile.TemporaryDirectory() as c:
            self.make_tree(p, ["a", "b"])
            self.make_tree(c, ["a", "b"])
            r=compare("a"*40, "b"*40, inventory(p), inventory(c))
            self.assertEqual(r["status"], "AUTO_REFRESH_REQUIRED")

    def test_deleted_records_fail_closed(self):
        with tempfile.TemporaryDirectory() as p, tempfile.TemporaryDirectory() as c:
            self.make_tree(p, ["a", "b"])
            self.make_tree(c, ["a"])
            r=compare("a"*40, "b"*40, inventory(p), inventory(c))
            self.assertEqual(r["status"], "AUTO_REFRESH_REQUIRED")
            self.assertEqual(r["removed_ids"], ["b"])

    def test_missing_projection_or_broken_name_blocks_all_readiness(self):
        with tempfile.TemporaryDirectory() as p:
            self.make_tree(p, ["a"], missing_projection=True)
            with self.assertRaisesRegex(ValueError, "AUTO_INVENTORY"):
                inventory(p)
        with tempfile.TemporaryDirectory() as p:
            self.make_tree(p, ["a"])
            (Path(p)/"data/auto/a.json").write_text('{"record_id":"another-id"}')
            with self.assertRaisesRegex(ValueError, "AUTO_INVENTORY"):
                inventory(p)

    def test_genuine_hf_snapshot_symlink_cache_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "datasets--Thorsu--miha-evidence"
            snapshot = root / "snapshots" / ("a" * 40)
            blobs = root / "blobs"
            blobs.mkdir(parents=True)
            canonical = snapshot / "data/auto/a.json"
            projection = snapshot / "data/auto_rows/a.jsonl"
            canonical.parent.mkdir(parents=True)
            projection.parent.mkdir(parents=True)
            raw = blobs / ("c" * 64)
            raw.write_text(json.dumps({"record_id": "a"}))
            canonical.symlink_to(raw)
            projection.write_text('{"id": "a"}\n')
            self.assertEqual(inventory(snapshot)["canonical_records"], 1)
            projection.unlink()
            projected = blobs / ("d" * 64)
            projected.write_text('{"id":"a"}\n')
            projection.symlink_to(projected)
            self.assertEqual(inventory(snapshot)["viewer_projection_rows"], 1)

    def test_symlink_escape_remains_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "datasets--Thorsu--miha-evidence"
            snapshot = root / "snapshots" / ("a" * 40)
            outside = Path(tmp) / "outside"
            outside.write_text(json.dumps({"record_id": "a"}))
            self.make_tree(snapshot, ["a"])
            canonical = snapshot / "data/auto/a.json"
            canonical.unlink()
            canonical.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "AUTO_INVENTORY"):
                inventory(snapshot)

    def test_invalid_sha_never_passes(self):
        for revision in ("main", "", "0"*39, True, None):
            with self.subTest(revision=revision):
                with self.assertRaisesRegex(ValueError, "AUTO_SHA"):
                    pinned_sha(revision)


if __name__ == "__main__":
    unittest.main()
