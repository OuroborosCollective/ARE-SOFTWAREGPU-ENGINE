"""Phase-4 offline worker regression: real subprocess isolation, no mocks.

Covers the issue-#6 evidence requirements: replay/hash readback, negative
deadline/memory/CPU/input contract tests and the bands-vs-tiles benefit gate.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np

from software_gpu.integrations.aurion.offline_render_worker import (
    JOB_PROTOCOL, RECEIPT_PROTOCOL, build_procedural_mesh, compare_backends,
    decide_activation, mesh_digest, run_job, validate_job,
)

CAMERA = {"yaw_degrees": 25.0, "pitch_degrees": 20.0, "center_y": 0.0,
          "x_half_extent": 1.6, "y_half_extent": 1.6}
BUDGET = {"deadline_seconds": 60, "memory_mb": 2048, "cpu_seconds": 120}


def make_job(**overrides):
    job = {"protocol": JOB_PROTOCOL, "authority": "offline-read-only",
           "fixture": {"kind": "procedural", "fixture_id": "phase4_test",
                       "seed": 686, "rings": 8, "segments": 16},
           "camera": dict(CAMERA),
           "render": {"pixels": 96, "repeats": 2, "backend": "tiles"},
           "budget": dict(BUDGET)}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(job.get(key), dict):
            job[key].update(value)
        else:
            job[key] = value
    return job


def synthetic_glb():
    # A visible front-facing double-sided triangle in real glTF2 binary.
    v = np.array([[-.2, 0.1, 0], [.2, 0.1, 0], [0, 1.6, 0]], dtype="<f4")
    idx = np.array([0, 1, 2], dtype="<u2")
    binary = v.tobytes() + idx.tobytes() + b"\0\0"
    obj = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(v.tobytes())},
            {"buffer": 0, "byteOffset": len(v.tobytes()),
             "byteLength": len(idx.tobytes())}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0,
    }
    meta = json.dumps(obj, separators=(",", ":")).encode()
    meta += b" " * ((-len(meta)) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(meta) + 8 + len(binary))
            + struct.pack("<I4s", len(meta), b"JSON") + meta
            + struct.pack("<I4s", len(binary), b"BIN\0") + binary)


class TestProceduralFixture(unittest.TestCase):
    def test_seeded_mesh_is_deterministic(self):
        v1, f1 = build_procedural_mesh(686, 8, 16)
        v2, f2 = build_procedural_mesh(686, 8, 16)
        v3, _ = build_procedural_mesh(687, 8, 16)
        self.assertEqual(mesh_digest(v1, f1), mesh_digest(v2, f2))
        self.assertNotEqual(mesh_digest(v1, f1), mesh_digest(v3, f2))
        self.assertEqual(v1.shape, (144, 3))
        self.assertEqual(f1.shape, (256, 3))
        self.assertTrue(np.isfinite(v1).all())
        self.assertLessEqual(float(np.abs(v1).max()), 0.8)


class TestJobContract(unittest.TestCase):
    def test_valid_job_passes(self):
        self.assertIsNotNone(validate_job(make_job()))

    def test_protocol_and_authority_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "JOB_PROTOCOL_INVALID"):
            validate_job(make_job(protocol="bogus"))
        with self.assertRaisesRegex(ValueError, "JOB_AUTHORITY_INVALID"):
            validate_job(make_job(authority="world-state-write"))

    def test_input_contract_negative_matrix(self):
        cases = [
            ({"fixture": {"seed": -1}}, "SEED_INVALID"),
            ({"fixture": {"seed": 1.5}}, "SEED_INVALID"),
            ({"fixture": {"seed": True}}, "SEED_INVALID"),
            ({"fixture": {"rings": 1}}, "MESH_RINGS_INVALID"),
            ({"fixture": {"rings": 65}}, "MESH_RINGS_INVALID"),
            ({"fixture": {"segments": 2}}, "MESH_SEGMENTS_INVALID"),
            ({"fixture": {"kind": "blend"}}, "FIXTURE_KIND_UNSUPPORTED"),
            ({"fixture": {"fixture_id": "../escape"}}, "FIXTURE_ID_INVALID"),
            ({"render": {"pixels": 1024}}, "PIXEL_BUDGET_INVALID"),
            ({"render": {"repeats": 1}}, "REPEAT_BUDGET_INVALID"),
            ({"render": {"backend": "cuda"}}, "BACKEND_UNSUPPORTED"),
            ({"budget": {"deadline_seconds": 0.001}}, "RESOURCE_BUDGET_INVALID"),
            ({"budget": {"memory_mb": 99999}}, "RESOURCE_BUDGET_INVALID"),
            ({"budget": {"cpu_seconds": 0}}, "RESOURCE_BUDGET_INVALID"),
            ({"camera": {"pitch_degrees": 90}}, "CAMERA_PARAMETER_OUT_OF_RANGE"),
            ({"camera": {"yaw_degrees": float("nan")}}, "CAMERA_PARAMETER_OUT_OF_RANGE"),
        ]
        for override, code in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex(ValueError, code):
                    validate_job(make_job(**override))


class TestIsolatedRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_replay_hash_readback_and_resource_receipt(self):
        receipt = run_job(make_job(), out_dir=self.root / "run")
        self.assertEqual(receipt["protocol"], RECEIPT_PROTOCOL)
        self.assertEqual(receipt["authority"], "offline-read-only")
        self.assertEqual(receipt["errors"], [])
        out = receipt["outcome"]
        self.assertTrue(out["repeat_byte_identical"])
        self.assertEqual(len(out["replay_hash_sha256"]), 64)
        self.assertGreater(out["covered_pixels"], 50)
        self.assertEqual(len(out["samples"]), 2)
        self.assertGreater(out["peak_rss_bytes"], 0)
        self.assertGreater(out["cpu_seconds_total"], 0)
        self.assertEqual(receipt["budget_compliance"],
                         {"deadline_ok": True, "memory_ok": True, "cpu_ok": True})
        self.assertEqual(out["fixture"]["kind"], "procedural")
        self.assertEqual(len(out["fixture"]["mesh_sha256"]), 64)
        image = self.root / "run" / out["image_file"]
        self.assertEqual(image.read_bytes()[:2], b"BM")
        self.assertEqual(out["image_bmp_sha256"],
                         hashlib.sha256(image.read_bytes()).hexdigest())
        on_disk = json.loads((self.root / "run" / "aurion-phase4-receipt.json")
                             .read_text("utf-8"))
        self.assertEqual(on_disk["receipt_sha256"], receipt["receipt_sha256"])

    def test_second_identical_job_replays_same_hashes(self):
        r1 = run_job(make_job(), out_dir=self.root / "a")
        r2 = run_job(make_job(), out_dir=self.root / "b")
        self.assertEqual(r1["outcome"]["replay_hash_sha256"],
                         r2["outcome"]["replay_hash_sha256"])
        self.assertEqual(r1["outcome"]["fixture"]["mesh_sha256"],
                         r2["outcome"]["fixture"]["mesh_sha256"])

    def test_deadline_exceeded_fails_closed_with_receipt(self):
        with self.assertRaisesRegex(TimeoutError, "WORKER_DEADLINE_EXCEEDED"):
            run_job(make_job(budget={"deadline_seconds": 0.02}),
                    out_dir=self.root / "dl")
        receipt = json.loads((self.root / "dl" / "aurion-phase4-receipt.json")
                             .read_text("utf-8"))
        self.assertIsNone(receipt["outcome"])
        self.assertEqual(receipt["errors"][0]["class"], "WORKER_DEADLINE_EXCEEDED")

    @unittest.skipUnless(sys.platform.startswith("linux"),
                         "peak-RSS receipt requires Linux rusage")
    def test_memory_budget_fails_closed(self):
        # 32 MB is below the interpreter's real peak RSS (~48 MB), so the
        # parent-side peak-RSS receipt gate must refuse success.
        with self.assertRaisesRegex(ValueError, "WORKER_MEMORY_BUDGET_EXCEEDED"):
            run_job(make_job(budget={"memory_mb": 32}), out_dir=self.root / "mem")

    def test_cpu_budget_fails_closed(self):
        # 0.05 s CPU is below interpreter startup, so the cooperative check
        # trips before the first repeat.
        with self.assertRaisesRegex(ValueError, "WORKER_CPU_BUDGET_EXCEEDED"):
            run_job(make_job(budget={"cpu_seconds": 0.05}), out_dir=self.root / "cpu")


class TestGlbFixtureMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.binary = synthetic_glb()
        (self.root / "tri.glb").write_bytes(self.binary)
        entry = {"bytes": len(self.binary),
                 "source_sha256": hashlib.sha256(self.binary).hexdigest(),
                 "vertices": 3, "triangles": 1, "meshes": 1,
                 "materials": 0, "images": 0}
        self.job = make_job(fixture={"kind": "glb", "fixture_id": "phase4_glb",
                                     "file": "tri.glb", "entry": entry},
                            camera={"yaw_degrees": 0, "pitch_degrees": 0,
                                    "center_y": .8, "x_half_extent": .5,
                                    "y_half_extent": 1})

    def test_glb_job_renders_pinned_source(self):
        receipt = run_job(self.job, model_dir=self.root, out_dir=self.root / "out")
        out = receipt["outcome"]
        self.assertEqual(out["fixture"]["kind"], "glb")
        self.assertEqual(out["fixture"]["source_sha256"],
                         self.job["fixture"]["entry"]["source_sha256"])
        self.assertEqual(out["fixture"]["triangles"], 1)
        self.assertTrue(out["repeat_byte_identical"])

    def test_glb_hash_mismatch_fails_closed(self):
        self.job["fixture"]["entry"]["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SOURCE_SHA256_MISMATCH"):
            run_job(self.job, model_dir=self.root, out_dir=self.root / "bad")

    def test_glb_path_escape_fails_closed(self):
        self.job["fixture"]["file"] = ".._.._tri.glb"  # fails name allowlist
        with self.assertRaisesRegex(ValueError, "GLB_NAME_INVALID"):
            validate_job(self.job)


class TestBenchmarkGate(unittest.TestCase):
    def test_bands_vs_tiles_identical_and_timed(self):
        vertices, faces = build_procedural_mesh(686, 6, 12)
        result = compare_backends(vertices, faces, CAMERA, pixels=64, repeats=2)
        self.assertTrue(result["image_identical"])
        self.assertIsNotNone(result["speedup"])
        self.assertGreater(result["speedup"], 0)
        for backend in ("bands", "tiles"):
            self.assertGreater(result["backends"][backend]["covered_pixels"], 20)

    def test_activation_decision_branches(self):
        win = decide_activation(1.47, True, min_speedup=1.10)
        self.assertEqual(win["decision"], "activate")
        slow = decide_activation(0.8, True)
        self.assertEqual(slow["decision"], "hold")
        self.assertIn("SLOWER_THAN_EXISTING_CPU_PATH", slow["reasons"])
        below = decide_activation(1.05, True, min_speedup=1.10)
        self.assertEqual(below["decision"], "hold")
        self.assertTrue(any(r.startswith("BENEFIT_BELOW_THRESHOLD")
                            for r in below["reasons"]))
        mismatch = decide_activation(2.0, False)
        self.assertEqual(mismatch["decision"], "hold")
        self.assertIn("IMAGE_MISMATCH_BETWEEN_BACKENDS", mismatch["reasons"])
        none = decide_activation(None, True)
        self.assertEqual(none["decision"], "hold")


if __name__ == "__main__":
    unittest.main()
