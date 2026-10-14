"""Real-file contracts for continuously growing MIHA Atomic SFT snapshots.

No untrusted live Viewer projections are admitted as train rows. These tests
exercise byte-hash-verified releases and deterministic full-replay shards; an
actual pinned HF canonical builder is exercised by the separate CI integration.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from software_gpu.training.auto_incremental import (
    inspect_release, plan_refresh, make_replay_shards, seal_plan,
    select_training_snapshot
)

H40=lambda c: c*40


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def build_release(folder, records, rows, evidence=H40("a"), bench=H40("c")):
    path=Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    content=b"".join(encoded({
        "id": id_, "origin_record_id": origin, "task_type": "node",
        "input_json": json.dumps({"topic": "measured", "sources": []}),
        "target_json": json.dumps({"status": "unverified", "claims": [],
                                   "used_sources": [], "missing_evidence": [],
                                   "next_paths": []})
    })+b"\n" for id_,origin in rows)
    (path/"train.jsonl").write_bytes(content)
    manifest={
        "builder_version":"2.1", "source_dataset":"Thorsu/miha-evidence",
        "dataset_revision":evidence, "benchmark_dataset":"Thorsu/miha-bench",
        "benchmark_revision":bench,"builder_code_sha256":"f"*64,
        "records": records,
        "training_example_ids":[p[0] for p in rows],
        "examples":len(rows), "overlap":{"overlap":0}, "question_answer_examples":0,
        "train_jsonl_sha256":hashlib.sha256(content).hexdigest(),
        "contains_hidden_chain_of_thought":False,
        "output_contract":"miha-five-key-v1"
    }
    (path/"build_manifest.json").write_bytes(encoded(manifest)+b"\n")
    return path


class DynamicAutoTrainingContracts(unittest.TestCase):
    def test_growth_uses_full_replay_not_new_only_and_has_no_static_557_limit(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            old=build_release(root/"old", {"r0":"a"*64}, [("a0","r0")])
            new=build_release(root/"new", {"r0":"a"*64,"r1":"b"*64},
                              [("a0","r0"),("a1","r1"),("a2","r1")],
                              evidence=H40("b"))
            plan=plan_refresh(inspect_release(old),inspect_release(new), "f"*40)
            self.assertEqual(plan["status"],"CANDIDATE_READY_FOR_REVIEW")
            self.assertEqual(plan["new_example_ids"],["a1","a2"])
            self.assertEqual(plan["all_training_example_ids"],["a0","a1","a2"])
            self.assertEqual(plan["strategy"],"full-corpus-replay")
            self.assertFalse(plan["training_started"])
            self.assertIsNone(plan["approved_atomic_revision"])
            self.assertFalse(plan["release_accepted"])
            shards=make_replay_shards(inspect_release(new),max_rows=2,seed=42)
            all_ids=[id_ for s in shards for id_ in s["ids"]]
            self.assertEqual(set(all_ids),{"a0","a1","a2"})
            self.assertEqual(len(all_ids),3)
            self.assertEqual(shards,make_replay_shards(inspect_release(new),max_rows=2,seed=42))
            self.assertTrue(all(len(s["ids"]) <= 2 for s in shards))

    def test_unchanged_live_snapshot_does_not_trigger_training(self):
        with tempfile.TemporaryDirectory() as t:
            root=build_release(t,{"r0":"a"*64},[("a0","r0")])
            old=inspect_release(root)
            plan=plan_refresh(old,old,"f"*40)
            self.assertEqual(plan["status"],"NO_CHANGE")
            self.assertEqual(plan["new_example_ids"],[])
            self.assertFalse(plan["training_started"])

    def test_changed_or_removed_approved_rows_require_manual_review(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            old=build_release(root/"old",{"r0":"a"*64,"r1":"b"*64},
                              [("a0","r0"),("b0","r1")])
            altered=build_release(root/"new",{"r0":"c"*64},[("a0","r0")],
                                  evidence=H40("b"))
            plan=plan_refresh(inspect_release(old),inspect_release(altered),"f"*40)
            self.assertEqual(plan["status"],"CORRECTION_REVIEW_REQUIRED")
            self.assertEqual(plan["removed_example_ids"],["b0"])
            self.assertEqual(plan["changed_record_ids"],["r0"])
            self.assertFalse(plan["training_started"])

    def test_identical_row_id_with_mutated_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            old=build_release(root/"old",{"r0":"a"*64},[("a0","r0")])
            new=build_release(root/"new",{"r0":"b"*64},[("a0","r0")],
                              evidence=H40("b"))
            plan=plan_refresh(inspect_release(old),inspect_release(new),"f"*40)
            self.assertEqual(plan["status"],"CORRECTION_REVIEW_REQUIRED")
            self.assertEqual(plan["changed_record_ids"],["r0"])

    def test_corrupted_bytes_manifest_or_holdout_overlap_never_pass(self):
        with tempfile.TemporaryDirectory() as t:
            root=build_release(t,{"r0":"a"*64},[("a0","r0")])
            with (root/"train.jsonl").open("ab") as fp: fp.write(b"x")
            with self.assertRaisesRegex(ValueError,"AUTO_RELEASE_HASH"):
                inspect_release(root)
        with tempfile.TemporaryDirectory() as t:
            root=build_release(t,{"r0":"a"*64},[("a0","r0")])
            manifest=json.loads((root/"build_manifest.json").read_text())
            manifest["overlap"]={"overlap":1}
            (root/"build_manifest.json").write_bytes(encoded(manifest)+b"\n")
            with self.assertRaisesRegex(ValueError,"AUTO_RELEASE_HOLDOUT"):
                inspect_release(root)

    def test_repeat_ids_and_orphan_origin_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=build_release(t,{"r0":"a"*64},[("a0","r0"),("a0","r0")])
            with self.assertRaisesRegex(ValueError,"AUTO_RELEASE_DUPLICATES"):
                inspect_release(root)
        with tempfile.TemporaryDirectory() as t:
            root=build_release(t,{"r0":"a"*64},[("a0","ghost")])
            with self.assertRaisesRegex(ValueError,"AUTO_RELEASE_ORIGIN"):
                inspect_release(root)

    def test_sharding_never_skips_or_splits_one_origin_silently(self):
        with tempfile.TemporaryDirectory() as t:
            root=build_release(t,{"r0":"a"*64},[("a0","r0"),("a1","r0"),("a2","r0")])
            with self.assertRaisesRegex(ValueError,"AUTO_REPLAY_SHARD"):
                make_replay_shards(inspect_release(root),max_rows=2)
            with self.assertRaisesRegex(ValueError,"AUTO_REPLAY_SHARD"):
                make_replay_shards(inspect_release(root),max_rows=0)

    def test_plan_receipt_digest_and_exact_identity(self):
        with tempfile.TemporaryDirectory() as t:
            root=build_release(t,{"r0":"a"*64},[("a0","r0")])
            p=plan_refresh(inspect_release(root),inspect_release(root),"f"*40)
            with tempfile.TemporaryDirectory() as output:
                path=Path(output)/"plan.json"
                report=seal_plan(p,path)
                self.assertEqual(report["sha256"],hashlib.sha256(encoded(p)).hexdigest())
                self.assertEqual(json.loads(path.read_text()),report)
                with self.assertRaisesRegex(FileExistsError,""):
                    seal_plan(p,path)
            with self.assertRaisesRegex(ValueError,"AUTO_RELEASE_PIN"):
                plan_refresh(inspect_release(root),inspect_release(root),"main")


    def test_approved_new_atomic_release_creates_immutable_dynamic_training_config(self):
        with tempfile.TemporaryDirectory() as t:
            release=inspect_release(build_release(
                t,{"r0":"a"*64,"r1":"b"*64},
                [("a0","r0"),("b0","r1")],evidence="b"*40))
            original={"code_revision":"c"*40,"base_revision":"d"*40,
                      "base_model":"Qwen/Qwen2.5-0.5B-Instruct",
                      "bench_revision":"c"*40,"atomic_revision":"e"*40,
                      "evidence_revision":"a"*40}
            cfg=select_training_snapshot(original,release,
                                         approved_atomic_sha="f"*40,
                                         current_evidence_sha="b"*40)
            self.assertEqual(cfg["evidence_revision"],"b"*40)
            self.assertEqual(cfg["atomic_revision"],"f"*40)
            self.assertEqual(cfg["code_revision"],original["code_revision"])
            self.assertEqual(cfg["base_revision"],original["base_revision"])
            self.assertEqual(cfg["bench_revision"],original["bench_revision"])
            self.assertEqual(original["evidence_revision"],"a"*40)

    def test_unapproved_or_lagging_atomic_blocks_dynamic_training(self):
        with tempfile.TemporaryDirectory() as t:
            release=inspect_release(build_release(t,{"r0":"a"*64},
                          [("a0","r0")], evidence="b"*40))
            original={"code_revision":"c"*40,"base_revision":"d"*40,
                      "base_model":"Qwen/Qwen2.5-0.5B-Instruct",
                      "bench_revision":"c"*40,"atomic_revision":"e"*40,
                      "evidence_revision":"a"*40}
            for wrong_rev in ("a"*40, "main", ""):
                with self.subTest(wrong_rev=wrong_rev), self.assertRaisesRegex(
                        ValueError,"AUTO_DYNAMIC"):
                    select_training_snapshot(original,release,
                        approved_atomic_sha="f"*40,
                        current_evidence_sha=wrong_rev)
            bad=dict(release)
            bad["sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"AUTO_DYNAMIC"):
                select_training_snapshot(original,bad,
                    approved_atomic_sha="f"*40,
                    current_evidence_sha="b"*40)
            with self.assertRaisesRegex(ValueError,"AUTO_DYNAMIC"):
                select_training_snapshot(original,release,
                    approved_atomic_sha="main",
                    current_evidence_sha="b"*40)


if __name__ == "__main__":
    unittest.main()
