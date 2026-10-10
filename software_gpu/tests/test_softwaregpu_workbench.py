"""Exercise the packaged workbench with actual renderer artifacts."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from software_gpu.benchmarks.compare_surface_plans import measure_scene
from software_gpu.benchmarks.compare_tile_backends import make_fixture

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins/softwaregpu-workbench"
SCRIPT = PLUGIN / "skills/softwaregpu-workbench/scripts/workbench.py"
spec = importlib.util.spec_from_file_location("tested_workbench", SCRIPT)
workbench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workbench)


class TestWorkbench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mesh, faces = make_fixture(3, .8)
        cls.actual = {"protocol": "are.surface-plan-benchmark.v1",
                      "results": [measure_scene("real", mesh, faces, 32, 1, 2, ablation=True)]}

    def export(self, folder, value):
        path = Path(folder) / "actual.json"
        path.write_text(json.dumps(value))
        return path

    def test_real_artifact_audit_and_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.export(folder, self.actual)
            _, result = workbench.audit(path)
            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["independent_rerender_performed"])
            analysis = workbench.analyze([path])
            self.assertEqual(len(analysis["cases"]), 1)
            self.assertFalse(analysis["runtime_gate_calibrated"])
            target = Path(folder) / "analysis.json"
            workbench.main(["analyze", str(path), "--output", str(target)])
            self.assertEqual(json.loads(target.read_text())["status"], "PASS")

    def test_mutated_real_stats_are_rejected(self):
        changed = copy.deepcopy(self.actual)
        changed["results"][0]["stats_ms"]["tiles"]["mad"] += 10
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "STATS_MISMATCH"):
                workbench.audit(self.export(folder, changed))

    def test_checkout_source_binding_rejects_old_or_unbound_reports(self):
        changed = copy.deepcopy(self.actual)
        name = "software_gpu/graphics/rasterizer.py"
        changed["source_paths_sha256"] = {n: workbench.digest(ROOT / n) for n in workbench.BENCHMARK_SOURCES}
        with tempfile.TemporaryDirectory() as folder:
            path = self.export(folder, changed)
            self.assertEqual(workbench.audit(path, ROOT)[1]["source_verification"],
                             "all-declared-sources-match-checkout")
            changed["source_paths_sha256"][name] = "0" * 64
            with self.assertRaisesRegex(ValueError, "CHECKOUT_SOURCE_MISMATCH"):
                workbench.audit(self.export(folder, changed), ROOT)
            changed["source_paths_sha256"][name] = workbench.digest(ROOT / name)
            changed["source_paths_sha256"]["../outside.py"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "SOURCE_PATH_INVALID"):
                workbench.audit(self.export(folder, changed), ROOT)
            with self.assertRaisesRegex(ValueError, "SOURCE_PATHS_REQUIRED"):
                workbench.audit(self.export(folder, self.actual), ROOT)

    def test_mutated_real_receipt_is_rejected(self):
        changed = copy.deepcopy(self.actual)
        changed["results"][0]["plans"]["abl-noscan-batch"]["binned_pairs"] += 1
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "PLAN_DIGEST_MISMATCH"):
                workbench.audit(self.export(folder, changed))

    def test_mutated_real_timing_and_claim_are_rejected(self):
        for mutator in (lambda c: c["samples_ms"]["tiles"].append(1.),
                        lambda c: c.update(gpu_parity_established=True)):
            changed = copy.deepcopy(self.actual)
            mutator(changed["results"][0])
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    workbench.audit(self.export(folder, changed))

    def test_inventory_is_static_and_pins_real_head(self):
        result = workbench.inspect(workbench.root_path(ROOT))
        self.assertFalse(result["runtime_activation_proven"])
        self.assertEqual(len(result["areas"]), 6)
        self.assertEqual(len(result["head"]), 40)
        self.assertIn("software_gpu/graphics/rasterizer.py", result["areas"]["core"])

    def test_manifest_identity_and_skills_match(self):
        main = json.loads((PLUGIN / "plugin.json").read_text())
        overlay = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(main, overlay)
        self.assertEqual(main["name"], "softwaregpu-workbench")
        interface = main["extensions"]["com.openai"]["interface"]
        self.assertLessEqual(len(interface["shortDescription"]), 30)
        self.assertTrue((PLUGIN / interface["logo"]).is_file())
        skill = (PLUGIN / "skills/softwaregpu-workbench/SKILL.md").read_text()
        self.assertIn("name: softwaregpu-workbench", skill)
        self.assertNotIn("TODO", skill)
