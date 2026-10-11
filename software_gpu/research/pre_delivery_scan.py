"""Release gate for a bounded Wolfram-derived IR and supplied numeric oracles.

Raw Wolfram parsing is performed offline by scan-symbolic-source.wl. This gate
independently validates the IR and executes the exact generated target sources.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np

from .symbolic_wave import compiled_python, emit_code, plan_ir


def scan_before_delivery(ir, cases, languages=("python", "javascript"), *, seconds=10):
    """Return code only after all selected targets match finite supplied oracles.

    These are caller-supplied oracle cases, not a universal mathematical proof.
    A missing requested target runtime blocks delivery instead of being skipped.
    """
    plan = plan_ir(ir)
    if (type(languages) not in (list, tuple) or not languages
            or any(type(v) is not str or v not in ("python", "javascript") for v in languages)
            or len(set(languages)) != len(languages)):
        raise ValueError("PRE_DELIVERY_LANGUAGES")
    if (type(cases) is not list or not 1 <= len(cases) <= 32
            or type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 30):
        raise ValueError("PRE_DELIVERY_CASE_OR_TIME_BUDGET")
    by_id = plan.node_map()
    for case in cases:
        if (type(case) is not dict or set(case) != {"inputs", "expected"}
                or type(case["expected"]) is not dict or set(case["expected"]) != set(plan.outputs)):
            raise ValueError("PRE_DELIVERY_ORACLE_NAMES")
        for name, value in case["expected"].items():
            if (type(value) is not np.ndarray or value.dtype != np.dtype(np.float32)
                    or value.shape != by_id[name].shape or not np.isfinite(value).all()):
                raise ValueError("PRE_DELIVERY_ORACLE_TYPE")
    node = None
    if "javascript" in languages:
        node = os.environ.get("CODEX_PRIMARY_RUNTIME_NODE") or shutil.which("node")
        if not node:
            raise ValueError("PRE_DELIVERY_NODE_REQUIRED")
    sources = {language: emit_code(ir, language) for language in languages}
    python = compiled_python(ir) if "python" in languages else None
    results = []
    with tempfile.TemporaryDirectory(prefix="are-scan-") as directory:
        js = Path(directory)/"kernel.cjs"
        if node:
            js.write_bytes(sources["javascript"].encode("utf-8"))
        for index, case in enumerate(cases):
            for language in languages:
                if language == "python":
                    actual = python(case["inputs"])
                    matches = all(actual[name].tobytes() == value.tobytes()
                                  for name, value in case["expected"].items())
                else:
                    # Reuse the Python input contract even in a JS-only release.
                    from .symbolic_wave import _inputs
                    _inputs(plan, case["inputs"])
                    payload = {k: {"dtype": "f32", "shape": list(v.shape), "data": v.ravel().tolist()}
                               for k, v in case["inputs"].items()}
                    try:
                        result = subprocess.run([node, str(js)], input=json.dumps(payload), text=True,
                                                capture_output=True, timeout=seconds, check=True)
                        actual = json.loads(result.stdout)
                    except (OSError, subprocess.SubprocessError, ValueError) as exc:
                        raise ValueError("PRE_DELIVERY_TARGET_FAILED") from exc
                    matches = (type(actual) is dict and set(actual) == set(plan.outputs)
                               and all(actual[name] == value.view(np.uint32).ravel().tolist()
                                       for name, value in case["expected"].items()))
                if not matches:
                    raise ValueError("PRE_DELIVERY_ORACLE_MISMATCH:" + language)
                results.append({"case": index, "target": language, "status": "PASS"})
    return {"status": "PASS", "sources": sources, "receipt": {
        "protocol": "are.pre-delivery-scan.v1", "graph_sha256": plan.sha256,
        "source_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sources.items()},
        "graph_nodes": len(plan.nodes), "waves": len(plan.waves),
        "oracle_cases": len(cases), "checks": results,
        "truth_layers": {"structure": "validated-local-IR", "dependencies": "validated-DAG",
                         "numerical": "passed-supplied-oracles", "external_world": "unknown"},
        "raw_wolfram_parser": "separate-offline-step; metadata is not an attestation",
        "authority": "pure-derived-computation-only"}}
