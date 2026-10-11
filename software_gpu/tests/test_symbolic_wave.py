"""Real ordered-f32 edge oracle and generated-code tests; no provider in CI."""
import ast
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

from software_gpu.graphics.geometry import edge_function
from software_gpu.research.symbolic_wave import (WaveRuntime, affected, compiled_python,
                                               emit_code, plan_ir)


FIXTURE = Path(__file__).parent / "fixtures" / "symbolic-edge.ir.json"
NODE = os.environ.get("CODEX_PRIMARY_RUNTIME_NODE") or shutil.which("node")


def fixture(shape=(2, 2, 3)):
    ir = json.loads(FIXTURE.read_text())
    for n in ir["nodes"]:
        n["shape"] = list(shape)
    return ir


def inputs(ir, seed=0):
    rng = np.random.default_rng(seed)
    return {n["id"]: rng.uniform(-1024, 1024, n["shape"]).astype(np.float32)
            for n in ir["nodes"] if n["op"] == "input"}


def oracle(values):
    return edge_function(np.stack((values["ax"], values["ay"])),
                         np.stack((values["bx"], values["by"])),
                         np.stack((values["px"], values["py"])))


def js_payload(values):
    return {k: {"dtype": "f32", "shape": list(v.shape), "data": v.ravel().tolist()}
            for k, v in values.items()}


def room_graph(count=32):
    """Independent pure rooms, followed by a fixed pairwise f32 reduction."""
    nodes = []
    def node(name, op, deps, level, room):
        nodes.append({"id": name, "op": op, "deps": deps,
                      "point": [level, room, 0, 0], "dtype": "f32", "shape": [1],
                      "color": {"input": "gray", "mul": "orange", "add": "green"}[op],
                      "contract": "ordered-f32-v1"})
    for i in range(count):
        node(f"x{i}", "input", [], 0, i)
        node(f"y{i}", "input", [], 0, i)
        node(f"r{i}", "mul", [f"x{i}", f"y{i}"], 1, i)
    current, level = [f"r{i}" for i in range(count)], 2
    while len(current) > 1:
        next_level = []
        for i in range(0, len(current), 2):
            name = f"sum{level}_{i//2}"
            node(name, "add", current[i:i+2], level, i//2)
            next_level.append(name)
        current, level = next_level, level + 1
    return {"protocol": "are.symbolic-wave-ir.v1", "syntax_valid": True,
            "nodes": nodes, "outputs": current}


def room_oracle(values, count=32):
    current = [values[f"x{i}"] * values[f"y{i}"] for i in range(count)]
    while len(current) > 1:
        current = [current[i] + current[i+1] for i in range(0, len(current), 2)]
    return current[0]


class TestSymbolicWave(unittest.TestCase):
    def test_recorded_wolfram_parser_and_independent_wave_plan(self):
        ir = fixture()
        self.assertTrue(ir["held_assignment_did_not_execute"])
        self.assertTrue(ir["symbolic_edge_identity"])
        plan = plan_ir(ir)
        self.assertEqual(len(plan.nodes), 13)
        self.assertEqual(len(plan.nodes[0].point), 4)
        self.assertEqual(plan.nodes[0].shape, (2, 2, 3))
        self.assertEqual(plan.waves, tuple(tuple(tuple(r) for r in w) for w in ir["wolfram_waves"]))

    def test_real_randomized_multidimensional_byte_parity(self):
        for shape in ((2, 2, 3), (32,), (8, 8)):
            ir = fixture(shape)
            generated = compiled_python(ir)
            for seed in range(15):
                with self.subTest(shape=shape, seed=seed):
                    data = inputs(ir, seed)
                    runtime = WaveRuntime(ir)
                    for change in (False, True):
                        if change:
                            data["px"].flat[0] += np.float32(.123)
                        expected = oracle(data).tobytes()
                        self.assertEqual(runtime.evaluate(data)["edge"].tobytes(), expected)
                        self.assertEqual(generated(data)["edge"].tobytes(), expected)

    def test_scan_local_edit_only_invalidates_dependency_descendants(self):
        ir, data = fixture(), inputs(fixture())
        runtime = WaveRuntime(ir)
        result = runtime.evaluate(data)
        self.assertEqual(len(runtime.last_receipt["executed_nodes"]), 7)
        result["edge"].fill(123)  # Caller cannot poison stored node results.
        copied = {k: v.copy() for k, v in data.items()}
        self.assertEqual(runtime.evaluate(copied)["edge"].tobytes(), oracle(data).tobytes())
        self.assertEqual(runtime.last_receipt["executed_nodes"], [])
        data["px"].flat[0] += np.float32(.25)
        self.assertEqual(runtime.evaluate(data)["edge"].tobytes(), oracle(data).tobytes())
        self.assertEqual(set(runtime.last_receipt["executed_nodes"]), {"rx", "left", "edge"})
        self.assertEqual(set(runtime.last_receipt["dirty_nodes"]), {"px", "rx", "left", "edge"})
        self.assertEqual(runtime.last_receipt["truth_layers"]["numerical"], "oracle-unchecked")
        self.assertEqual(runtime.last_receipt["truth_layers"]["external_world"], "unknown")
        for array in runtime._values.values():
            with self.assertRaises(ValueError):
                array.setflags(write=True)
        for v in data.values():
            v += np.float32(.5)
        runtime.evaluate(data)
        self.assertEqual(len(runtime.last_receipt["executed_nodes"]), 7)

    def test_reject_invalid_graphs_and_false_color_equivalence(self):
        bad = []
        for key, value in (("op", "run"), ("dtype", "f64"), ("contract", "fastmath"),
                           ("color", "orange"), ("id", "x');import os;#"),
                           ("deps", ["ax"]), ("deps", [4, "ax"]),
                           ("shape", [0]), ("shape", [True]), ("shape", [65537]),
                           ("shape", [1, 1, 1, 1, 1]), ("point", [-1]), ("point", [])):
            ir = fixture(); ir["nodes"][6][key] = value; bad.append(ir)
        ir = fixture(); ir["nodes"][6]["extra"] = "effect"; bad.append(ir)
        ir = fixture(); ir["nodes"][0]["id"] = "ay"; bad.append(ir)
        ir = fixture(); ir["nodes"][6]["deps"] = ["missing", "ax"]; bad.append(ir)
        ir = fixture(); ir["nodes"][6]["shape"] = [3]; bad.append(ir)
        ir = fixture(); ir["nodes"][6]["deps"] = ["edge", "ax"]; bad.append(ir)
        ir = fixture(); ir["nodes"][6]["point"] = [1]; bad.append(ir)
        ir = fixture((65536, 2)); bad.append(ir)
        for output in ([], ["missing"], ["edge", "edge"], [4]):
            ir = fixture(); ir["outputs"] = output; bad.append(ir)
        for ir in ({}, None, {"protocol": "bad"}, {**fixture(), "syntax_valid": False},
                   {**fixture(), "nodes": []}, {**fixture(), "nodes": [None]}, *bad):
            with self.subTest(ir=ir), self.assertRaises(ValueError):
                plan_ir(ir)
        with self.assertRaisesRegex(ValueError, "UNKNOWN_EVENT"):
            affected(plan_ir(fixture()), {"world-knows-everything"})

    def test_input_contract_both_runtime_and_generated_code(self):
        ir = fixture()
        engines = (WaveRuntime(ir).evaluate, compiled_python(ir))
        bad = []
        for value in (np.ones((12,), np.float32), np.ones((2, 2, 3), np.float64),
                      np.full((2, 2, 3), np.nan, np.float32),
                      np.full((2, 2, 3), np.inf, np.float32), [1, 2, 3]):
            data = inputs(ir); data["px"] = value; bad.append(data)
        data = inputs(ir); del data["px"]; bad.append(data)
        data = inputs(ir); data["extra"] = data["px"]; bad.append(data)
        for engine in engines:
            for data in bad:
                with self.assertRaises(ValueError): engine(data)

    def test_overflow_is_transactional_and_does_not_claim_numeric_truth(self):
        ir, data = fixture(), inputs(fixture())
        runtime = WaveRuntime(ir)
        runtime.evaluate(data)
        prior = {k: v for k, v in runtime._values.items()}
        bad = {k: v.copy() for k, v in data.items()}
        bad["bx"].fill(1e30); bad["py"].fill(1e30)
        with self.assertRaisesRegex(ValueError, "NONFINITE_RESULT"): runtime.evaluate(bad)
        self.assertIsNone(runtime.last_receipt)
        self.assertTrue(all(runtime._values[k] is v for k, v in prior.items()))
        with self.assertRaisesRegex(ValueError, "NONFINITE_RESULT"): compiled_python(ir)(bad)
        self.assertEqual(runtime.evaluate(data)["edge"].tobytes(), oracle(data).tobytes())
        self.assertEqual(runtime.last_receipt["executed_nodes"], [])

    def test_addition_and_multiple_colored_regions(self):
        ir = fixture()
        n = copy.deepcopy(ir["nodes"][6]); n.update(id="sum", op="add", color="green", deps=["ax", "ay"])
        ir["nodes"].append(n); ir["outputs"].append("sum")
        data = inputs(ir)
        runtime = WaveRuntime(ir)
        out = runtime.evaluate(data)
        self.assertEqual(out["sum"].tobytes(), (data["ax"] + data["ay"]).tobytes())
        self.assertEqual(compiled_python(ir)(data)["sum"].tobytes(), out["sum"].tobytes())
        self.assertEqual({r["color"] for r in runtime.last_receipt["regions"]}, {"blue", "orange", "green"})
        self.assertIn("Math.fround(x +", emit_code(ir, "javascript"))

    def test_empty_operator_waves_and_language_registry(self):
        ir = fixture(); ir["nodes"] = ir["nodes"][:1]; ir["outputs"] = ["ax"]
        data = inputs(ir)
        self.assertEqual(plan_ir(ir).waves, ())
        self.assertEqual(WaveRuntime(ir).evaluate(data)["ax"].tobytes(), data["ax"].tobytes())
        self.assertEqual(compiled_python(ir)(data)["ax"].tobytes(), data["ax"].tobytes())
        ast.parse(emit_code(ir, "python"))
        for language in ("rust", "C++", "__import__('os')"):
            with self.assertRaisesRegex(ValueError, "LANGUAGE_UNSUPPORTED"): emit_code(ir, language)

    def test_room_map_reduction_and_local_change(self):
        ir = room_graph()
        plan = plan_ir(ir)
        self.assertEqual(len(plan.nodes), 127)
        self.assertEqual(len(plan.waves), 6)
        self.assertEqual(len(plan.waves[0][0]), 32)
        generated = compiled_python(ir)
        for seed in range(15):
            data = inputs(ir, seed)
            runtime = WaveRuntime(ir)
            output = ir["outputs"][0]
            self.assertEqual(runtime.evaluate(data)[output].tobytes(), room_oracle(data).tobytes())
            self.assertEqual(len(runtime.last_receipt["executed_nodes"]), 63)
            runtime.evaluate(data)
            self.assertEqual(runtime.last_receipt["executed_nodes"], [])
            data["x0"][0] += np.float32(.125)
            expected = room_oracle(data).tobytes()
            self.assertEqual(runtime.evaluate(data)[output].tobytes(), expected)
            self.assertEqual(generated(data)[output].tobytes(), expected)
            self.assertEqual(len(runtime.last_receipt["executed_nodes"]), 6)
            self.assertIn("r0", runtime.last_receipt["executed_nodes"])
        with self.assertRaisesRegex(ValueError, "SCHEMA"):
            plan_ir(room_graph(64))  # 255 nodes exceed the explicit prototype cap.

    @unittest.skipUnless(NODE, "Node.js needed only for cross-language execution")
    def test_room_reduction_javascript_actual_bits(self):
        ir = room_graph()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rooms.cjs"
            path.write_text(emit_code(ir, "javascript"))
            for seed in range(5):
                data = inputs(ir, seed)
                result = subprocess.run([NODE, str(path)], input=json.dumps(js_payload(data)),
                                        text=True, capture_output=True, timeout=20, check=True)
                expected = room_oracle(data).view(np.uint32).ravel().tolist()
                self.assertEqual(json.loads(result.stdout)[ir["outputs"][0]], expected)

    @unittest.skipUnless(NODE, "Node.js needed only for cross-language execution")
    def test_actual_javascript_float32_bits_against_renderer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kernel.cjs"
            for shape in ((2, 2, 3), (32,), (8, 8)):
                ir = fixture(shape); path.write_text(emit_code(ir, "javascript"))
                for seed in range(12):
                    data = inputs(ir, seed)
                    if seed == 0:
                        for value in data.values(): value.flat[:4] = [0., -0., 1e-30, -1e-30]
                    result = subprocess.run([NODE, str(path)], input=json.dumps(js_payload(data)),
                                            text=True, capture_output=True, timeout=20, check=True)
                    self.assertEqual(json.loads(result.stdout)["edge"], oracle(data).view(np.uint32).ravel().tolist())
            bad = inputs(ir); bad["px"] = bad["px"].astype(np.float64)
            payload = js_payload(bad); payload["px"]["dtype"] = "f64"
            result = subprocess.run([NODE, str(path)], input=json.dumps(payload), text=True,
                                    capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("INPUT_TYPE", result.stderr)

    @unittest.skipUnless(NODE, "Node.js needed only for cross-language execution")
    def test_javascript_rejects_names_overflow_and_handles_identifier_collision(self):
        ir = fixture(); data = inputs(ir)
        for n in ir["nodes"]:
            if n["id"] == "ax": n["id"] = "values"
            n["deps"] = ["values" if x == "ax" else x for x in n["deps"]]
        data["values"] = data.pop("ax")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kernel.cjs"; path.write_text(emit_code(ir, "javascript"))
            payload = js_payload(data)
            result = subprocess.run([NODE, str(path)], input=json.dumps(payload), text=True,
                                    capture_output=True, timeout=20, check=True)
            self.assertEqual(json.loads(result.stdout)["edge"], compiled_python(ir)(data)["edge"].view(np.uint32).ravel().tolist())
            payload["extra"] = payload["values"]
            result = subprocess.run([NODE, str(path)], input=json.dumps(payload), text=True,
                                    capture_output=True, timeout=20)
            self.assertIn("INPUT_NAMES", result.stderr)
            data["bx"].fill(1e30); data["py"].fill(1e30)
            result = subprocess.run([NODE, str(path)], input=json.dumps(js_payload(data)), text=True,
                                    capture_output=True, timeout=20)
            self.assertIn("NONFINITE_RESULT", result.stderr)
