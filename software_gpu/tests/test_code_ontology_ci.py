"""Contract tests for optional, static Code Ontology Companion integration.

Fixture objects here are *unit-test inputs*, never actual ARE runtime evidence.
The real Companion CLI is executed separately by the CI workflow.
"""
import tempfile
from pathlib import Path
import unittest

from scripts.code_ontology_ci import (
    check_bundle,
    require_query_symbol,
    summarize_static_impact,
    assert_local_artifacts,
    validate_diff,
    validate_preflight,
)


class CodeOntologyContractTests(unittest.TestCase):
    def test_requires_all_official_regular_files_inside_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "skills" / "manage-code-ontology" / "scripts"
            scripts.mkdir(parents=True)
            for name in ("companion.py", "code_ontology_core.py", "local_llm.py", "code_reference.py"):
                (scripts / name).write_text("# unit fixture\n", encoding="utf-8")
            self.assertEqual(check_bundle(scripts / "companion.py"), scripts / "companion.py")
            (scripts / "local_llm.py").unlink()
            with self.assertRaisesRegex(ValueError, "BUNDLE_INCOMPLETE"):
                check_bundle(scripts / "companion.py")
            try:
                (scripts / "local_llm.py").symlink_to(scripts / "companion.py")
            except OSError:
                # Windows runners without symlink privileges still exercise
                # the same fail-closed non-regular helper-file contract.
                (scripts / "local_llm.py").mkdir()
            with self.assertRaisesRegex(ValueError, "BUNDLE_NOT_REGULAR"):
                check_bundle(scripts / "companion.py")

    def test_preflight_accepts_python_without_pretending_cpp_is_supported(self):
        value = {
            "status": "ready", "source_file_count": 219,
            "supported_languages": {"Python": 219}, "skipped": {"unsupported_extensions": 7},
        }
        self.assertEqual(validate_preflight(value), 219)
        with self.assertRaisesRegex(ValueError, "NO_PYTHON"):
            validate_preflight({"status": "ready", "source_file_count": 2,
                               "supported_languages": {"Java": 2}})
        with self.assertRaisesRegex(ValueError, "PREFLIGHT_STATUS"):
            validate_preflight({"status": "no_supported_sources",
                               "source_file_count": 0, "supported_languages": {}})

    def test_symbol_search_uses_real_path_and_pinned_snapshot(self):
        fixture = {"snapshotId": "snap-test-only", "matches": [
            {"id": "python-symbol-123", "name": "SoftwareRasterizer",
             "language": "Python", "path": "software_gpu/graphics/rasterizer.py",
             "type": "PythonClass"},
        ]}
        self.assertEqual(
            require_query_symbol(fixture, "SoftwareRasterizer",
                                 "software_gpu/graphics/rasterizer.py",
                                 "snap-test-only"), "python-symbol-123")
        with self.assertRaisesRegex(ValueError, "SNAPSHOT_MISMATCH"):
            require_query_symbol(fixture, "SoftwareRasterizer",
                                 "software_gpu/graphics/rasterizer.py", "other")
        with self.assertRaisesRegex(ValueError, "SYMBOL_NOT_FOUND"):
            require_query_symbol(fixture, "SoftwareRasterizer",
                                 "software_gpu/graphics/geometry.py", "snap-test-only")

    def test_impact_remains_static_and_does_not_claim_live_executions(self):
        evidence = [{"rule_id": "python.import.v1", "basis": "observed",
                     "runtime_status": "runtime_unknown",
                     "path": "software_gpu/graphics/rasterizer.py",
                     "line_start": 3, "line_end": 3}]
        value = {"status": "ok", "snapshotId": "snap-fixture",
                 "impact_count": 1, "impact": [
                    {"depth": 1, "relationship": "imports", "evidence": evidence,
                     "node": {"name": "framebuffer"}, "path": [
                         {"type": "imports", "evidence": evidence}
                     ]}
                 ]}
        result = summarize_static_impact(value, "snap-fixture")
        self.assertEqual(result["related_nodes"], 1)
        self.assertEqual(result["source_evidence"], 1)
        self.assertEqual(result["runtime"], "not_measured")
        with self.assertRaisesRegex(ValueError, "IMPACT_STATUS"):
            summarize_static_impact({"status": "ambiguous", "impact": []}, "snap-fixture")

    def test_visual_graph_and_rdf_exist_but_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots" / "snap-check"
            snapshots.mkdir(parents=True)
            html = snapshots / "graph.html"
            rdf = snapshots / "ontology.ttl"
            html.write_text("<html>" + "x" * 256 + "</html>", encoding="utf-8")
            rdf.write_text("@prefix co: <https://example.invalid/> ." + "x" * 256,
                           encoding="utf-8")
            self.assertEqual(
                assert_local_artifacts({
                    "visualization": str(html),
                    "portableRdf": str(rdf),
                }, root), "local_only")
            html.unlink()
            html.symlink_to(rdf)
            with self.assertRaisesRegex(ValueError, "ARTIFACT_SYMLINK"):
                assert_local_artifacts({"visualization": str(html),
                                        "portableRdf": str(rdf)}, root)

    def test_architecture_guard_runs_for_any_pr_not_only_doc_edits(self):
        workflow = (Path(__file__).resolve().parents[2] /
                    ".github/workflows/code-ontology-companion.yml")
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("  pull_request:", text)
        self.assertIn("    branches: [main]", text)
        self.assertNotIn("    paths:", text)
        self.assertIn("permissions:\n  contents: read", text)
        self.assertIn("sha256sum --check --status", text)
        self.assertNotIn("actions/upload-artifact", text)

    def test_diff_refuses_analyzer_reinterpretation_as_source_change(self):
        source_delta = {"status": "ok", "changeBasis": "source_change",
                        "counts": {"nodesAdded": 1, "nodesRemoved": 0,
                                   "edgesAdded": 0, "edgesRemoved": 0}}
        result = validate_diff(source_delta)
        self.assertEqual(result["change_basis"], "source_change")
        with self.assertRaisesRegex(ValueError, "DIFF_NOT_SOURCE_CHANGE"):
            validate_diff(dict(source_delta, changeBasis="analyzer_reinterpretation"))


if __name__ == "__main__":
    unittest.main()
