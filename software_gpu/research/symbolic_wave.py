"""Bounded research DSL: typed colored regions, dependency waves and codegen.

This is not imported by the renderer. Wolfram parses the held source offline;
this module validates its finite IR and executes only pure ordered f32 ops.
Colors/coordinates describe work. Numerical equivalence requires runtime tests.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import re

import numpy as np


PROTOCOL = "are.symbolic-wave-ir.v1"
COLORS = {"input": "gray", "add": "green", "sub": "blue", "mul": "orange"}
OPS = {"add": np.add, "sub": np.subtract, "mul": np.multiply}
FIELDS = {"id", "op", "deps", "point", "dtype", "shape", "color", "contract"}


@dataclass(frozen=True)
class Node:
    id: str
    op: str
    deps: tuple
    point: tuple
    dtype: str
    shape: tuple
    color: str
    contract: str


@dataclass(frozen=True)
class Plan:
    nodes: tuple
    inputs: tuple
    outputs: tuple
    waves: tuple
    sha256: str

    def node_map(self):
        return {n.id: n for n in self.nodes}


def plan_ir(ir):
    """Validate the local schema and DAG; parser metadata is not a certificate."""
    if (type(ir) is not dict or ir.get("protocol") != PROTOCOL
            or ir.get("syntax_valid") is not True or type(ir.get("nodes")) is not list
            or not 1 <= len(ir["nodes"]) <= 128):
        raise ValueError("SYMBOLIC_WAVE_SCHEMA")
    nodes = []
    for row in ir["nodes"]:
        if type(row) is not dict or set(row) != FIELDS:
            raise ValueError("SYMBOLIC_WAVE_NODE_FIELDS")
        if (type(row["id"]) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,31}", row["id"]) is None
                or type(row["op"]) is not str or row["op"] not in COLORS
                or row["dtype"] != "f32" or row["contract"] != "ordered-f32-v1"
                or row["color"] != COLORS[row["op"]]):
            raise ValueError("SYMBOLIC_WAVE_NODE_CONTRACT")
        if (type(row["deps"]) is not list or any(type(v) is not str for v in row["deps"])
                or len(row["deps"]) != (0 if row["op"] == "input" else 2)):
            raise ValueError("SYMBOLIC_WAVE_ARITY")
        for key, maximum, minimum in (("point", 8, 0), ("shape", 4, 1)):
            value = row[key]
            if (type(value) is not list or not 1 <= len(value) <= maximum
                    or any(type(v) is not int or not minimum <= v <= 65536 for v in value)):
                raise ValueError("SYMBOLIC_WAVE_DIMENSIONS")
        nodes.append(Node(**{key: tuple(value) if key in ("deps", "point", "shape") else value
                             for key, value in row.items()}))
    by_id = {n.id: n for n in nodes}
    if len(by_id) != len(nodes) or len({len(n.point) for n in nodes}) != 1:
        raise ValueError("SYMBOLIC_WAVE_IDENTITIES_OR_SPACE")
    if sum(math.prod(n.shape) for n in nodes) > 1_048_576:
        raise ValueError("SYMBOLIC_WAVE_CELL_BUDGET")
    for n in nodes:
        if any(dep not in by_id or by_id[dep].shape != n.shape for dep in n.deps):
            raise ValueError("SYMBOLIC_WAVE_DEPENDENCY_TYPE")
    outputs = ir.get("outputs")
    if (type(outputs) is not list or not outputs or any(type(v) is not str or v not in by_id for v in outputs)
            or len(set(outputs)) != len(outputs)):
        raise ValueError("SYMBOLIC_WAVE_OUTPUTS")
    inputs = tuple(sorted(n.id for n in nodes if n.op == "input"))
    done = set(inputs)
    pending = {n.id for n in nodes} - done
    waves = []
    while pending:
        ready = sorted(node for node in pending if set(by_id[node].deps) <= done)
        if not ready:
            raise ValueError("SYMBOLIC_WAVE_CYCLE")
        regions = {}
        for name in ready:
            n = by_id[name]
            signature = (n.op, n.dtype, n.shape, n.contract)
            regions.setdefault(signature, []).append(name)
        waves.append(tuple(tuple(region) for region in regions.values()))
        done.update(ready)
        pending.difference_update(ready)
    canonical = json.dumps({"nodes": ir["nodes"], "outputs": outputs}, sort_keys=True, separators=(",", ":"))
    return Plan(tuple(nodes), inputs, tuple(outputs), tuple(waves), hashlib.sha256(canonical.encode()).hexdigest())


def affected(plan, changed):
    """Scan the finite dependency graph; never infer arbitrary external facts."""
    dirty = set(changed)
    if not dirty <= set(plan.inputs):
        raise ValueError("SYMBOLIC_WAVE_UNKNOWN_EVENT")
    by_id = plan.node_map()
    for wave in plan.waves:
        for region in wave:
            for name in region:
                if dirty.intersection(by_id[name].deps):
                    dirty.add(name)
    return dirty


def _inputs(plan, values):
    if type(values) is not dict or set(values) != set(plan.inputs):
        raise ValueError("SYMBOLIC_WAVE_INPUT_NAMES")
    by_id = plan.node_map()
    for name, value in values.items():
        if (type(value) is not np.ndarray or value.dtype != np.dtype(np.float32)
                or value.shape != by_id[name].shape or not np.isfinite(value).all()):
            raise ValueError("SYMBOLIC_WAVE_INPUT_TYPE")


def _frozen(value):
    return np.frombuffer(value.tobytes(order="C"), dtype=np.float32).reshape(value.shape)


class WaveRuntime:
    """Transactional pure-node reuse. Full input content scan detects edits."""
    def __init__(self, ir):
        self.plan = plan_ir(ir)
        self._values, self._fingerprints = {}, {}
        self.last_receipt = None

    def evaluate(self, inputs):
        self.last_receipt = None
        plan, by_id = self.plan, self.plan.node_map()
        _inputs(plan, inputs)
        fingerprints = {name: hashlib.sha256(
            repr(value.strides).encode() + value.tobytes(order="C")).hexdigest()
                        for name, value in inputs.items()}
        changed = sorted(name for name in plan.inputs if fingerprints[name] != self._fingerprints.get(name))
        dirty = affected(plan, changed)
        values = dict(self._values)
        for name in changed:
            values[name] = _frozen(inputs[name])
        regions, executed = [], []
        for wave_index, wave in enumerate(plan.waves, 1):
            for region in wave:
                selected = tuple(name for name in region if name in dirty)
                if not selected:
                    continue
                n = by_id[selected[0]]
                left = np.stack([values[by_id[name].deps[0]] for name in selected])
                right = np.stack([values[by_id[name].deps[1]] for name in selected])
                with np.errstate(all="ignore"):
                    result = OPS[n.op](left, right)
                if not np.isfinite(result).all():
                    raise ValueError("SYMBOLIC_WAVE_NONFINITE_RESULT")
                for i, name in enumerate(selected):
                    values[name] = _frozen(result[i])
                executed.extend(selected)
                regions.append({"wave": wave_index, "op": n.op, "color": n.color,
                                "dtype": n.dtype, "shape": list(n.shape), "nodes": list(selected),
                                "points": [list(by_id[name].point) for name in selected]})
        self._values, self._fingerprints = values, fingerprints
        self.last_receipt = {"protocol": "are.symbolic-wave-runtime.v1", "graph_sha256": plan.sha256,
            "scanned_inputs": len(inputs), "graph_nodes": len(plan.nodes), "waves": len(plan.waves),
            "changed_inputs": changed, "dirty_nodes": sorted(dirty), "executed_nodes": executed,
            "regions": regions, "truth_layers": {"structure": "validated-local-IR",
            "dependencies": "validated-DAG", "numerical": "oracle-unchecked",
            "external_world": "unknown"}, "authority": "pure-derived-computation-only"}
        return {name: values[name].copy() for name in plan.outputs}


def emit_code(ir, language):
    """Translate only this whitelisted IR; no arbitrary source eval or rewrites."""
    if language not in ("python", "javascript"):
        raise ValueError("SYMBOLIC_WAVE_LANGUAGE_UNSUPPORTED")
    plan = plan_ir(ir)
    by_id = plan.node_map()
    if language == "python":
        lines = ["import numpy as np", "", "def run(inputs):", "    values = {}",
                 f"    if type(inputs) is not dict or set(inputs) != set({list(plan.inputs)!r}):",
                 "        raise ValueError('SYMBOLIC_WAVE_INPUT_NAMES')"]
        for name in plan.inputs:
            lines += [f"    value = inputs[{name!r}]",
                f"    if type(value) is not np.ndarray or value.dtype != np.dtype(np.float32) or value.shape != {by_id[name].shape!r} or not np.isfinite(value).all():",
                "        raise ValueError('SYMBOLIC_WAVE_INPUT_TYPE')", f"    values[{name!r}] = value"]
        for wave in plan.waves:
            for region in wave:
                op = {"add": "add", "sub": "subtract", "mul": "multiply"}[by_id[region[0]].op]
                args = [[f"values[{by_id[name].deps[i]!r}]" for name in region] for i in (0, 1)]
                lines += ["    with np.errstate(all='ignore'):",
                    f"        group = np.{op}(np.stack([{', '.join(args[0])}]), np.stack([{', '.join(args[1])}]))",
                    "    if not np.isfinite(group).all():", "        raise ValueError('SYMBOLIC_WAVE_NONFINITE_RESULT')"]
                lines += [f"    values[{name!r}] = group[{i}]" for i, name in enumerate(region)]
        lines += ["    return {" + ", ".join(f"{name!r}: values[{name!r}].copy()" for name in plan.outputs) + "}"]
    else:
        lines = ["'use strict';", "function run(inputs) {", "  const values = Object.create(null);", "  let item;",
                 f"  if (JSON.stringify(Object.keys(inputs).sort()) !== {json.dumps(json.dumps(list(plan.inputs), separators=(',', ':')))} ) throw Error('SYMBOLIC_WAVE_INPUT_NAMES');"]
        for name in plan.inputs:
            n = by_id[name]
            lines += [f"  item = inputs[{json.dumps(name)}];",
                f"  if (!item || item.dtype !== 'f32' || JSON.stringify(item.shape) !== {json.dumps(json.dumps(list(n.shape), separators=(',', ':')))} || !Array.isArray(item.data) || item.data.length !== {math.prod(n.shape)} || !item.data.every(x => Number.isFinite(x) && Object.is(x, Math.fround(x)))) throw Error('SYMBOLIC_WAVE_INPUT_TYPE');",
                f"  values[{json.dumps(name)}] = item.data.slice();"]
        for wave in plan.waves:
            for region in wave:
                for name in region:
                    n = by_id[name]
                    symbol = {"add": "+", "sub": "-", "mul": "*"}[n.op]
                    lines += [f"  values[{json.dumps(name)}] = values[{json.dumps(n.deps[0])}].map((x, i) => Math.fround(x {symbol} values[{json.dumps(n.deps[1])}][i]));",
                        f"  if (!values[{json.dumps(name)}].every(Number.isFinite)) throw Error('SYMBOLIC_WAVE_NONFINITE_RESULT');"]
        lines += ["  return {" + ",".join(json.dumps(name) + ": values[" + json.dumps(name) + "]" for name in plan.outputs) + "};",
            "}", "module.exports = {run};", "if (require.main === module) {",
            "  const result = run(JSON.parse(require('node:fs').readFileSync(0, 'utf8')));",
            "  const bits = {}; const view = new DataView(new ArrayBuffer(4));",
            "  for (const [name, values] of Object.entries(result)) bits[name] = values.map(x => {view.setFloat32(0, x, true); return view.getUint32(0, true);});",
            "  console.log(JSON.stringify(bits));", "}"]
    return "\n".join(lines) + "\n"


def compiled_python(ir):
    """Compile our validated template, never a caller-provided Python string."""
    namespace = {}
    exec(compile(emit_code(ir, "python"), "<are-symbolic-wave-generated>", "exec"), namespace)
    return namespace["run"]
