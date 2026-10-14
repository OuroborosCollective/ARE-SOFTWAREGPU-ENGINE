"""MIHA Training V2 contracts: actual local checkpoint bytes and fail-closed policy.

No model weights are faked or downloaded by these unit tests. They validate
planning, checkpoint integrity, holdout acceptance and opt-in device gates;
runtime training and inference remain separate evidence requirements.
"""
import json
from pathlib import Path
import tempfile
import unittest

from software_gpu.training.v2_contracts import (
    build_sweep, select_experiment, training_identity, seal_checkpoint,
    verify_checkpoint, quality_gate, require_gpu_research_gate, profile_threads
)

CFG = {
    "code_revision": "a" * 40,
    "evidence_revision": "b" * 40,
    "atomic_revision": "c" * 40,
    "bench_revision": "d" * 40,
    "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
    "base_revision": "7ae557604adf67be50417f59c2c2f167def9a775",
}


class TrainingV2Contracts(unittest.TestCase):
    def test_sweep_is_bounded_unique_and_does_not_run_training(self):
        plan = build_sweep(CFG, renderer_sha="e" * 40)
        self.assertEqual(len(plan["candidates"]), 9)
        self.assertEqual({x["rank"] for x in plan["candidates"]}, {8, 16, 32})
        self.assertEqual({x["learning_rate"] for x in plan["candidates"]}, {"0.00005", "0.0001", "0.0002"})
        self.assertEqual(plan["thread_trials"], [2, 4, 6, 8])
        self.assertFalse(plan["training_started"])
        self.assertFalse(plan["gpu_allowed"])
        self.assertFalse(plan["release_accepted"])
        self.assertEqual(len({x["id"] for x in plan["candidates"]}), 9)
        self.assertEqual(select_experiment(plan, "r16-lr0.0001")["rank"], 16)
        with self.assertRaisesRegex(ValueError, "V2_UNKNOWN_EXPERIMENT"):
            select_experiment(plan, "r64-lr0.003")

    def test_config_preserves_pinned_cpu_base_and_immutable_sources(self):
        plan = build_sweep(CFG, "e" * 40)
        self.assertEqual(plan["pins"]["base_revision"], CFG["base_revision"])
        for field, bad in (("base_model", "Some/OtherModel"), ("code_revision", "main"),
                           ("base_revision", "f" * 40), ("atomic_revision", "")):
            with self.subTest(field=field):
                modified = dict(CFG, **{field: bad})
                with self.assertRaisesRegex(ValueError, "V2_PIN_OR_POLICY"):
                    build_sweep(modified, "e" * 40)
        with self.assertRaisesRegex(ValueError, "V2_PIN_OR_POLICY"):
            build_sweep(CFG, "main")

    def test_thread_options_are_explicit_and_bounded(self):
        self.assertEqual(profile_threads([2, 4, 6, 8]), [2, 4, 6, 8])
        for options in ([0], [12], [2, 2], [True], [], [4, 8, 6]):
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, "V2_THREADS"):
                    profile_threads(options)

    def identity(self):
        plan = build_sweep(CFG, "e" * 40)
        candidate = select_experiment(plan, "r16-lr0.0001")
        return training_identity(CFG, "f" * 64, "e" * 40, candidate, "cpu", 4)

    def build_real_state_files(self, folder, step=5):
        path = Path(folder) / f"checkpoint-{step}"
        path.mkdir()
        (path / "optimizer.pt").write_bytes(b"actual serialized optimizer data bytes")
        (path / "scheduler.pt").write_bytes(b"actual scheduler data bytes")
        (path / "rng_state.pth").write_bytes(b"real serialized RNG bytes")
        (path / "adapter_model.safetensors").write_bytes(b"adapter snapshot bytes")
        (path / "trainer_state.json").write_text(json.dumps({"global_step": step}))
        return path

    def test_checkpoint_readback_requires_identity_and_actual_file_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.build_real_state_files(tmp)
            identity = self.identity()
            seal_checkpoint(path, identity)
            self.assertTrue(verify_checkpoint(path, identity))
            (path / "optimizer.pt").write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "V2_CHECKPOINT_HASH"):
                verify_checkpoint(path, identity)

    def test_resume_rejects_different_seed_rank_device_or_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.build_real_state_files(tmp)
            identity = self.identity()
            seal_checkpoint(path, identity)
            for field, altered in (("seed", 99), ("rank", 32), ("device", "cuda"),
                                   ("dataset_sha256", "0" * 64)):
                with self.subTest(field=field):
                    changed = dict(identity, **{field: altered})
                    with self.assertRaisesRegex(ValueError, "V2_CHECKPOINT_IDENTITY"):
                        verify_checkpoint(path, changed)
            (path / "rng_state.pth").unlink()
            with self.assertRaisesRegex(ValueError, "V2_CHECKPOINT_MISSING"):
                verify_checkpoint(path, identity)

    def test_checkpoint_step_and_symlink_are_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.build_real_state_files(tmp, step=5)
            identity = self.identity()
            seal_checkpoint(path, identity)
            (path / "trainer_state.json").write_text(json.dumps({"global_step": 4}))
            with self.assertRaisesRegex(ValueError, "V2_CHECKPOINT_STEP"):
                verify_checkpoint(path, identity)
        with tempfile.TemporaryDirectory() as tmp:
            path = self.build_real_state_files(tmp)
            seal_checkpoint(path, self.identity())
            (path / "optimizer.pt").unlink()
            (path / "optimizer.pt").symlink_to(path / "scheduler.pt")
            with self.assertRaisesRegex(ValueError, "V2_CHECKPOINT_MISSING"):
                verify_checkpoint(path, self.identity())

    def test_holdout_gate_requires_actual_complete_ids_and_no_regression(self):
        report = {
            "benchmark_revision": "d" * 40,
            "adapter_reload_verified": True,
            "candidate": {"records": [{"id": "case-1", "parse_ok": True},
                                      {"id": "case-2", "parse_ok": True}],
                          "summary": {"score": 0.82, "parse_fail": 0,
                            "allowed_source_compliance": 1.0, "forbidden_source_compliance": 1.0}},
            "baseline": {"summary": {"score": 0.78, "parse_fail": 1,
                "allowed_source_compliance": 0.95, "forbidden_source_compliance": 1.0}},
            "regressions": [],
        }
        value = quality_gate(report, ["case-1", "case-2"], "d" * 40)
        self.assertTrue(value["gates_passed"])
        self.assertFalse(value["release_accepted"])
        report["candidate"]["records"].pop()
        with self.assertRaisesRegex(ValueError, "V2_HOLDOUT_INCOMPLETE"):
            quality_gate(report, ["case-1", "case-2"], "d" * 40)
        report["candidate"]["records"].append({"id": "case-2", "parse_ok": True})
        report["candidate"]["summary"]["score"] = 0.70
        self.assertFalse(quality_gate(report, ["case-1", "case-2"], "d" * 40)["gates_passed"])

    def test_gpu_fails_closed_against_current_owner_policy(self):
        policy = {"device": "cpu", "gpu_allowed": False}
        for flag in (False, True):
            with self.subTest(flag=flag):
                with self.assertRaisesRegex(ValueError, "V2_GPU_POLICY_DENIED"):
                    require_gpu_research_gate(policy, allow=flag, visible_devices=1,
                                              bf16_supported=True, vram_bytes=24 * 1024**3)
        approved = {"device": "cpu", "gpu_allowed": True}
        with self.assertRaisesRegex(ValueError, "V2_GPU_EXPLICIT_OPT_IN"):
            require_gpu_research_gate(approved, allow=False, visible_devices=1,
                                      bf16_supported=True, vram_bytes=24 * 1024**3)
        with self.assertRaisesRegex(ValueError, "V2_GPU_RESOURCE_GATE"):
            require_gpu_research_gate(approved, allow=True, visible_devices=1,
                                      bf16_supported=True, vram_bytes=8 * 1024**3)
        self.assertTrue(require_gpu_research_gate(approved, allow=True, visible_devices=1,
                                                 bf16_supported=True, vram_bytes=24 * 1024**3))


if __name__ == "__main__":
    unittest.main()
