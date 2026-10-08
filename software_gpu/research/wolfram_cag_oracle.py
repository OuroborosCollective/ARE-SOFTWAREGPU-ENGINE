"""Optional Wolfram-CAG-style geometry oracle: offline evidence only.

No Wolfram dependency, provider key, network access, renderer hooks or
Aurion gameplay authority. Golden expected values were evaluated by a real
Wolfram Language kernel; CI performs independent Python CPU comparisons.
The authenticated Wolfram CAG HTTP component is deliberately NOT called.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from fractions import Fraction

PROTOCOL = "are.wolfram-cag-geometry.v1"
_SOURCE_BOUNDARY = "numeric_geometry_only"
_FIXTURE = Path(__file__).resolve().parents[2] / "evidence" / "wolfram-cag-geometry.v1.json"
_RATIONAL = re.compile(r"-?(?:0|[1-9][0-9]{0,8})(?:/[1-9][0-9]{0,8})?\Z")


def rational(value: str) -> Fraction:
    """Accept ONLY small exact rational literals, never Wolfram/Python code."""
    if not isinstance(value, str) or not _RATIONAL.fullmatch(value):
        raise ValueError("CAG_RATIONAL_LITERAL_INVALID")
    return Fraction(value)


def get_fixture(path: Path | None = None) -> tuple[dict, str]:
    """Return a bounded checked-in oracle and a hash over its exact bytes.

    No arbitrary path is accepted by runtime consumers; custom paths are
    exposed solely for negative tests on temporary evidence files.
    """
    fixture_path = path if path is not None else _FIXTURE
    with fixture_path.open("rb") as stream:
        raw = stream.read(16_385)
    if not raw or len(raw) > 16_384:
        raise ValueError("CAG_FIXTURE_SIZE_INVALID")
    doc = json.loads(raw)
    if not isinstance(doc, dict) or doc.get("protocol") != PROTOCOL:
        raise ValueError("CAG_PROTOCOL_INVALID")
    if doc.get("mutationAuthority") != "none" or doc.get("sourceBoundary") != _SOURCE_BOUNDARY:
        raise ValueError("CAG_AUTHORITY_BOUNDARY_INVALID")
    if doc.get("oracle") != "Wolfram Language exact rational computation":
        raise ValueError("CAG_SOURCE_INVALID")
    if set(doc) != {"protocol", "mutationAuthority", "sourceBoundary", "oracle",
                    "nearClip", "perspective", "msaa", "sharedEdge"}:
        raise ValueError("CAG_SCHEMA_INVALID")
    for case in ("nearClip", "perspective", "msaa", "sharedEdge"):
        if not isinstance(doc[case], dict):
            raise ValueError("CAG_CASE_INVALID")
    for case in ("nearClip", "perspective", "msaa"):
        for vertex in doc[case]["clipVertices"]:
            if len(vertex) != 4:
                raise ValueError("CAG_VERTEX_SHAPE_INVALID")
            for component in vertex:
                rational(component)
    for point in doc["nearClip"]["nearIntersections"]:
        if len(point) != 4:
            raise ValueError("CAG_INTERSECTION_SHAPE_INVALID")
        for component in point:
            rational(component)
    for component in doc["perspective"]["screenBarycentric"]:
        rational(component)
    for point in doc["msaa"]["samplePoints"]:
        if len(point) != 2:
            raise ValueError("CAG_SAMPLE_SHAPE_INVALID")
        for component in point:
            rational(component)
    rational(doc["nearClip"]["remainingAreaXY"])
    rational(doc["perspective"]["expectedBlue"])
    if (len(doc["msaa"]["coverage"]) != 4 or
            any(type(x) is not bool for x in doc["msaa"]["coverage"])):
        raise ValueError("CAG_COVERAGE_SHAPE_INVALID")
    return doc, hashlib.sha256(raw).hexdigest()


def main() -> None:
    doc, source_sha256 = get_fixture()
    result = {
        "protocol": PROTOCOL,
        "status": "OFFLINE_GOLDEN_AVAILABLE",
        "sourceBoundary": _SOURCE_BOUNDARY,
        "mutationAuthority": "none",
        "fixtureSha256": source_sha256,
        "caseCount": 4,
        "wolframKernelPreviouslyEvaluated": True,
        "authenticatedCagApiCallExecuted": False,
        "gitRevision": os.environ.get("GITHUB_SHA", "local"),
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
