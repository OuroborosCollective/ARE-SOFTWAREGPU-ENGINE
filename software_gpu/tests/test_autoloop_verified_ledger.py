"""Only real, GitHub-attested full CPU A/B receipts may advance a sweep.

Fixtures are artificial admission inputs, NEVER performance measurements.
"""
import hashlib
import json
import unittest
from software_gpu.benchmarks import autoloop_verified_ledger as ledger
from software_gpu.benchmarks.autoloop_cpu_ab import SOURCE_PATHS, TARGET
from software_gpu.tests.test_autoloop_cpu_ab import make_profiles

CAT = {
    "protocol": "are.autoloop-cpu-catalog.v1",
    "version": "2026-10-25-v1",
    "candidates": ["scalar-fastpath", "batch-fastpath"],
    "scenes": ["tiny"],
    "pixels": [64, 128],
    "workers": [1],
    "rounds": 2,
    "pairs_per_round": 15,
}
RUN_URL = "https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/"
REPO = "OuroborosCollective/ARE-SOFTWAREGPU-ENGINE"

def attested(run_id, outcome="no_gain", *, dirty=False):
    source = f"{run_id:040x}"
    baseline = "b" * 40
    hashes = {name: "a" * 64 for name in SOURCE_PATHS}
    modified = dict(hashes)
    modified[TARGET] = "c" * 64
    profiles = make_profiles(10, 9 if outcome == "accepted" else 10)
    score = (10 / 9) if outcome == "accepted" else 1.0
    receipt = {
        "protocol": "are.autoloop-cpu-ab-run.v1",
        "baseline_commit": baseline,
        "source_commit": source,
        "source_sha256": modified,
        "baseline_source_sha256": hashes,
        "render_scope": "whole-draw CPU RGBA8 plus float32 depth",
        "environment": {"runner": "github-hosted", "cpu": "CI-contract-fixture",
                        "python": "3.12", "numpy": "2.5", "workers": [1, 2]},
        "profiles": profiles,
        "candidate_dirty_shader": dirty,
        "smoke_only": False,
        "outcome": outcome,
        "score": score,
        "profile_count": 20,
    }
    receipt["sha256"] = hashlib.sha256(json.dumps(
        receipt, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    run = {
        "id": run_id, "name": "Autoloop CPU A/B (GitHub runner only)",
        "event": "workflow_dispatch", "status": "completed",
        "conclusion": "success", "repository": {"full_name": REPO},
        "head_sha": source, "run_attempt": 1,
    }
    return {"run": run, "receipt": receipt}

def entries(n=3):
    return [{"sweep": sweep, "candidate": candidate, "run_id": sweep * 100 + idx}
            for sweep in range(1, n + 1)
            for idx, candidate in enumerate(CAT["candidates"], start=1)]

def evaluate(rows, changed=None):
    proofs = {item["run_id"]: attested(item["run_id"]) for item in rows}
    if changed:
        changed(proofs)
    return ledger.verify_authenticated_runs(
        CAT, {"protocol": "are.autoloop-cpu-run-ledger.v1",
              "catalog_version": CAT["version"], "runs": rows},
        lambda run_id: proofs[run_id])

class TestAttestedPlateau(unittest.TestCase):
    def test_three_complete_sweeps_only(self):
        self.assertTrue(evaluate(entries())["completed"])
        self.assertEqual(evaluate(entries(2))["consecutive_no_gain_sweeps"], 2)
        self.assertFalse(evaluate(entries()[:-1])["completed"])

    def test_acceptance_resets_streak(self):
        def accept(p):
            p[201] = attested(201, "accepted")
        self.assertFalse(evaluate(entries(), accept)["completed"])

    def test_self_asserted_ci_boolean_not_used(self):
        rows = entries()
        rows[0]["ci_verified"] = True
        with self.assertRaisesRegex(ValueError, "LEDGER_ENTRY_FIELDS"):
            evaluate(rows)

    def test_bad_digest_rejected(self):
        with self.assertRaisesRegex(ValueError, "RECEIPT_DIGEST"):
            evaluate(entries(), lambda p: p[101]["receipt"].update({"sha256": "0" * 64}))

    def test_not_real_full_run_rejected(self):
        with self.assertRaisesRegex(ValueError, "FULL_RUN_REQUIRED"):
            evaluate(entries(), lambda p: p[101]["receipt"].update({"smoke_only": True}))

    def test_wrong_ci_head_rejected(self):
        with self.assertRaisesRegex(ValueError, "CI_HEAD"):
            evaluate(entries(), lambda p: p[101]["run"].update({"head_sha": "f" * 40}))

    def test_wrong_run_workflow_or_event_rejected(self):
        with self.assertRaisesRegex(ValueError, "CI_WORKFLOW"):
            evaluate(entries(), lambda p: p[101]["run"].update({"name": "unrelated passing tests"}))
        with self.assertRaisesRegex(ValueError, "CI_EVENT"):
            evaluate(entries(), lambda p: p[101]["run"].update({"event": "pull_request"}))

    def test_changed_source_outside_shader_blocked(self):
        def change(p):
            p[101]["receipt"]["source_sha256"]["software_gpu/graphics/framebuffer.py"] = "d" * 64
            body = {k:v for k,v in p[101]["receipt"].items() if k != "sha256"}
            p[101]["receipt"]["sha256"] = hashlib.sha256(json.dumps(
                body, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, "NON_TARGET_SOURCE_CHANGED"):
            evaluate(entries(), change)

    def test_duplicate_reused_and_gapped_runs_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "LEDGER_DUPLICATE_RUN"):
            evaluate(entries() + [{"sweep": 4, "candidate": "scalar-fastpath", "run_id": 101}])
        with self.assertRaisesRegex(ValueError, "LEDGER_DUPLICATE_CANDIDATE"):
            evaluate(entries() + [{"sweep": 1, "candidate": "scalar-fastpath", "run_id": 999}])
        data = entries()
        data[0]["sweep"] = 0
        with self.assertRaisesRegex(ValueError, "LEDGER_SWEEP"):
            evaluate(data)

    def test_markdown_ledger_roundtrip_and_missing(self):
        self.assertEqual(ledger.parse_markdown_ledger("# State\n"), None)
        doc = "# State\n\n<!-- ARE_CPU_RUN_LEDGER_BEGIN -->\n" + json.dumps({
            "protocol": "are.autoloop-cpu-run-ledger.v1",
            "catalog_version": CAT["version"], "runs": entries(1),
        }) + "\n<!-- ARE_CPU_RUN_LEDGER_END -->\n"
        self.assertEqual(ledger.parse_markdown_ledger(doc)["runs"], entries(1))
        with self.assertRaisesRegex(ValueError, "LEDGER_MARKERS"):
            ledger.parse_markdown_ledger(doc.replace("<!-- ARE_CPU_RUN_LEDGER_END -->", ""))
if __name__ == "__main__":
    unittest.main()
