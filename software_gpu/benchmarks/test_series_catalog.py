"""Deterministic newest-first registration of tests, separate from CPU-speed ranks.

This reads source-controlled test metadata only. It does not execute or
measure tests and cannot promote test registrations to benchmark results.
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "evidence/test-series-catalog-v1.json"
PROTOCOL = "are.test-series-catalog.v1"
KEYS = {"id", "introduced", "title", "module", "surface", "status"}
SURFACES = {"test", "core", "production", "persistence", "effects", "runtime-projection"}
TOKEN = re.compile(r"[a-z][a-z0-9-]{2,79}\Z")
PATH = re.compile(r"software_gpu/tests/test_[a-z0-9_]+\.py\Z")


def _require(condition, reason):
    if not condition:
        raise ValueError("CATALOG_" + reason)


def validate_catalog(document):
    _require(isinstance(document, dict) and set(document) == {"protocol", "tests"}
             and document["protocol"] == PROTOCOL, "PROTOCOL")
    rows = document["tests"]
    _require(isinstance(rows, list) and len(rows) <= 100, "BUDGET")
    found = set()
    for row in rows:
        _require(isinstance(row, dict) and set(row) == KEYS, "FIELDS")
        identifier = row["id"]
        _require(isinstance(identifier, str) and TOKEN.fullmatch(identifier),
                 "IDENTIFIER")
        _require(identifier not in found, "DUPLICATE")
        found.add(identifier)
        raw = row["introduced"]
        _require(isinstance(raw, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw)),
                 "DATE")
        try:
            _require(date.fromisoformat(raw).isoformat() == raw, "DATE")
        except ValueError as exc:
            raise ValueError("CATALOG_DATE") from exc
        _require(isinstance(row["title"], str) and
                 1 <= len(row["title"]) <= 85 and
                 not any(c in row["title"] for c in "|\r\n<>"), "TITLE")
        _require(isinstance(row["module"], str) and PATH.fullmatch(row["module"])
                 and (ROOT / row["module"]).is_file(), "TEST_MODULE_MISSING")
        _require(row["surface"] in SURFACES, "SURFACE")
        _require(row["status"] == "registered", "STATUS")
    return sorted(rows, key=lambda r: (-date.fromisoformat(r["introduced"]).toordinal(),
                                       r["id"]))


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def render_catalog(document):
    rows = validate_catalog(document)
    lines = [
        "## Neue Testreihen (neueste zuerst, getrennt von CPU-Leistungsrängen)",
        "",
        "**Regel:** Neuere registrierte Testreihen stehen stets oben; gleiche Daten"
        " werden nach stabiler Test-ID sortiert. Registrierung ist **kein"
        " CI-Erfolg, FPS-Wert oder Benchmark-Sieg**. Erst originale SHA-"
        " gebundene CPU-Receipts und bestandene vollständige Frame-/Depth-Gates"
        " dürfen in eine vergleichbare Leistungsrangliste übernommen werden.",
        "",
        "| Hinzugefügt | Testreihe | Projektfläche | Prüfstand | CPU-Zeit / FPS |",
        "|:--|:--|:--|:--|:--|",
    ]
    for row in rows:
        lines.append(f'| {row["introduced"]} | {row["title"]} '
                     f'(\`{row["module"]}\`) | {row["surface"]} | '
                     "**registriert; CI separat prüfen** | **nicht gemessen** |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_catalog(load_catalog()))
