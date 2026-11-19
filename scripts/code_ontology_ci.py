"""Optional Code Ontology Companion 0.6.0 CI adapter for ARE SoftwareGPU.

Runs the upstream *verified* source-only analyzer in an isolated temporary
workspace. It neither executes ARE source nor stores portable ontology data
in this repository or uploads graph artifacts. No production runtime claims.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any


EXPECTED_FILES = ("companion.py", "code_ontology_core.py",
                  "local_llm.py", "code_reference.py")
EXPECTED_RELATIVE = Path("skills/manage-code-ontology/scripts/companion.py")


def check_bundle(companion: Path) -> Path:
    """Refuse missing, symlinked, or displaced upstream helper files."""
    companion = Path(companion)
    scripts = companion.parent
    if tuple(companion.parts[-len(EXPECTED_RELATIVE.parts):]) != EXPECTED_RELATIVE.parts:
        # Unit tests may create this exact suffix beneath their temp root.
        raise ValueError("BUNDLE_PATH_INVALID")
    for name in EXPECTED_FILES:
        p = scripts / name
        if not p.exists():
            raise ValueError("BUNDLE_INCOMPLETE")
        if p.is_symlink() or not stat.S_ISREG(p.lstat().st_mode):
            raise ValueError("BUNDLE_NOT_REGULAR")
        if p.resolve().parent != scripts.resolve():
            raise ValueError("BUNDLE_ESCAPED")
    return companion


def validate_preflight(report: dict[str, Any]) -> int:
    if report.get("status") != "ready":
        raise ValueError("PREFLIGHT_STATUS")
    languages = report.get("supported_languages", {})
    if not isinstance(languages, dict) or not isinstance(languages.get("Python"), int):
        raise ValueError("NO_PYTHON")
    count = languages["Python"]
    if count < 1 or report.get("source_file_count", 0) < count:
        raise ValueError("NO_PYTHON")
    return count


def require_query_symbol(result: dict[str, Any], name: str,
                         relative_path: str, snapshot: str) -> str:
    if result.get("snapshotId") != snapshot:
        raise ValueError("SNAPSHOT_MISMATCH")
    matches = [n for n in result.get("matches", [])
               if n.get("name") == name and n.get("path") == relative_path
               and n.get("language") == "Python" and isinstance(n.get("id"), str)]
    if len(matches) != 1:
        raise ValueError("SYMBOL_NOT_FOUND")
    return matches[0]["id"]


def summarize_static_impact(result: dict[str, Any], snapshot: str) -> dict[str, Any]:
    if result.get("status") != "ok" or result.get("snapshotId") != snapshot:
        raise ValueError("IMPACT_STATUS")
    impacts = result.get("impact", [])
    if not isinstance(impacts, list):
        raise ValueError("IMPACT_INVALID")
    evidence = [part for edge in impacts for part in edge.get("evidence", [])
                if isinstance(part, dict) and all(
                    isinstance(part.get(k), str)
                    for k in ("rule_id", "basis", "runtime_status"))]
    return {
        "related_nodes": len(impacts),
        "source_evidence": len(evidence),
        "truncated": bool(result.get("truncated")),
        "runtime": "not_measured",
        "interpretation": "static_possible_dependencies_only",
    }


def validate_diff(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "ok" or result.get("changeBasis") != "source_change":
        raise ValueError("DIFF_NOT_SOURCE_CHANGE")
    counts = result.get("counts", {})
    if not isinstance(counts, dict):
        raise ValueError("DIFF_COUNTS_INVALID")
    return {
        "change_basis": "source_change",
        "changes": {k: v for k, v in counts.items() if isinstance(v, int)},
        "runtime": "not_measured",
    }


def assert_local_artifacts(status: dict[str, Any], workspace: Path) -> str:
    """Prove the offline HTML/RDF outputs exist without publishing their bytes."""
    base = Path(workspace).resolve(strict=True)
    for field, expected in (("visualization", "graph.html"),
                            ("portableRdf", "ontology.ttl")):
        raw = status.get(field)
        if not isinstance(raw, str):
            raise ValueError("ARTIFACT_MISSING")
        path = Path(raw)
        if path.is_symlink():
            raise ValueError("ARTIFACT_SYMLINK")
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("ARTIFACT_MISSING") from exc
        if (not resolved.is_relative_to(base)
                or resolved.name != expected):
            raise ValueError("ARTIFACT_ESCAPED")
        if not resolved.is_file() or resolved.stat().st_size < 80:
            raise ValueError("ARTIFACT_EMPTY")
    return "local_only"


def _run(companion: Path, *args: str) -> dict[str, Any]:
    process = subprocess.run(
        [sys.executable, str(companion), *args],
        check=False, capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    if process.returncode != 0:
        # Do not emit stdout/stderr: may include private workspace paths.
        raise ValueError("COMPANION_COMMAND_FAILED:" + args[0] +
                         ":" + str(process.returncode))
    try:
        result = json.loads(process.stdout)
    except (ValueError, TypeError) as exc:
        raise ValueError("COMPANION_NON_JSON:" + args[0]) from exc
    if not isinstance(result, dict):
        raise ValueError("COMPANION_NON_OBJECT:" + args[0])
    return result


def _find_bundle(root: Path) -> Path:
    found = list(root.glob("**/skills/manage-code-ontology/scripts/companion.py"))
    if len(found) != 1:
        raise ValueError("BUNDLE_NOT_UNIQUE")
    return check_bundle(found[0])


def real_checkout_smoke(bundle: Path, repo: Path, output: Path) -> dict[str, Any]:
    companion = _find_bundle(bundle)
    repo = repo.resolve(strict=True)
    if (repo / ".git").is_dir() is False:
        raise ValueError("CHECKOUT_NOT_GIT_REPO")
    if not (repo / "software_gpu/graphics/rasterizer.py").is_file():
        raise ValueError("CHECKOUT_NOT_ARE")
    doctor = _run(companion, "doctor", "--repo", str(repo))
    if doctor.get("companionVersion") != "0.6.0" or doctor.get("status") != "ok":
        raise ValueError("COMPANION_VERSION_MISMATCH")
    preflight = _run(companion, "preflight", "--repo", str(repo))
    python_files = validate_preflight(preflight)
    with tempfile.TemporaryDirectory(prefix="are-code-ontology-", dir=output) as tmp:
        temp = Path(tmp)
        workspace = temp / "real-repo-snapshot"
        initialized = _run(companion, "init", "--repo", str(repo),
                           "--workspace", str(workspace), "--authorized",
                           "--label", "ARE-SOFTWAREGPU-ENGINE")
        if initialized.get("status") != "promoted":
            raise ValueError("INIT_NOT_PROMOTED")
        status = _run(companion, "status", "--workspace", str(workspace))
        if status.get("status") != "ok" or status.get("freshness") != "current":
            raise ValueError("NOT_FRESH")
        assert_local_artifacts(status, workspace)
        snapshot = status["snapshotId"]
        if snapshot != initialized.get("snapshotId"):
            raise ValueError("SNAPSHOT_MISMATCH")
        query = _run(companion, "query", "--workspace", str(workspace),
                     "--snapshot", snapshot, "--term", "SoftwareRasterizer",
                     "--path-prefix", "software_gpu/graphics", "--limit", "100")
        symbol_id = require_query_symbol(query, "SoftwareRasterizer",
                                          "software_gpu/graphics/rasterizer.py",
                                          snapshot)
        impact = _run(companion, "impact", "--workspace", str(workspace),
                      "--snapshot", snapshot, "--symbol", symbol_id,
                      "--depth", "2", "--direction", "both", "--limit", "100")
        impact_result = summarize_static_impact(impact, snapshot)
        history = _run(companion, "history", "--workspace", str(workspace))
        if not any(item.get("snapshotId") == snapshot
                   for item in history.get("snapshots", [])):
            raise ValueError("HISTORY_SNAPSHOT_MISSING")
        unchanged = _run(companion, "sync", "--workspace", str(workspace))
        if unchanged.get("status") != "no_change" or unchanged.get("snapshotId") != snapshot:
            raise ValueError("SYNC_NOT_IDEMPOTENT")
        # Exercise the official snapshot diff on an isolated, genuine source
        # transition; do not modify a single byte of the checked-out ARE repo.
        fixture = temp / "isolated-diff-source"
        fixture.mkdir()
        (fixture / "module.py").write_text("def original():\n    return 1\n", encoding="utf-8")
        fixture_workspace = temp / "isolated-diff-snapshot"
        first = _run(companion, "init", "--repo", str(fixture),
                     "--workspace", str(fixture_workspace), "--authorized")
        (fixture / "module.py").write_text(
            "def original():\n    return 1\n\ndef added():\n    return original()\n",
            encoding="utf-8")
        second = _run(companion, "sync", "--workspace", str(fixture_workspace))
        if second.get("status") != "promoted" or second.get("snapshotId") == first.get("snapshotId"):
            raise ValueError("DIFF_FIXTURE_SNAPSHOT_MISSING")
        diff = _run(companion, "diff", "--workspace", str(fixture_workspace),
                    "--before", first["snapshotId"], "--after", second["snapshotId"])
        delta = validate_diff(diff)
        if delta["changes"].get("nodesAdded", 0) < 1:
            raise ValueError("DIFF_ADD_NOT_FOUND")
        # Do not export source manifest, absolute paths, or embedded graph.
        # They remain in the ephemeral GitHub runner's private temp directory.
        summary = {
            "protocol": "are.code-ontology-companion-ci.v1",
            "repository": "OuroborosCollective/ARE-SOFTWAREGPU-ENGINE",
            "analyzer_version": "0.6.0",
            "source_files_python": python_files,
            "snapshot_id": snapshot,
            "freshness": status["freshness"],
            "query": {"symbol": "SoftwareRasterizer",
                      "path": "software_gpu/graphics/rasterizer.py",
                      "match": "confirmed_in_static_snapshot"},
            "impact": impact_result,
            "history": "current_snapshot_found",
            "unchanged_sync": "no_change",
            "isolated_source_diff": delta,
            "target_code_executed": False,
            "runtime_evidence": "not_measured",
            "native_cpp_coverage": "not_supported",
            "graph_exported_or_uploaded": False,
        }
        # Sensitive snapshot IDs are confined to runner memory (not printed).
        summary.pop("snapshot_id")
        return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = real_checkout_smoke(args.bundle, args.repo, args.output_dir)
    # Do not upload even this summary as a GitHub Actions artifact.
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
