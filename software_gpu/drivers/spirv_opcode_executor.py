"""Restricted *actual* SPIR-V SSA execution in ARE's Python tile renderer.

Only the proven GLSL 450 pass-through vertex/fragment subset is admitted.
Every module must pass the genuine SPIRV-Tools validator first. Unknown
instructions, stages, missing outputs or unsupported resource paths fail
closed. This is not NIR, the native C++ shader backend or a Vulkan ICD.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

import numpy as np

from software_gpu.drivers.spirv_preflight import validate_module
from software_gpu.graphics.shader import Shader


class UnsupportedSpirv(ValueError):
    pass


# Actual glslang 450 pass-through modules: metadata, types, variables and
# straight-line SSA. Reject texture, pointer arithmetic, call, branch,
# control-flow, atomics, compute, descriptor, memory barrier and other opcodes.
_ALLOWED = frozenset({
    3, 5, 6, 11, 14, 15, 16, 17, 19, 21, 22, 23, 28, 30, 32, 33,
    43, 54, 56, 59, 61, 62, 65, 71, 72, 80, 81, 248, 253,
})
_METADATA = frozenset({
    3, 5, 6, 11, 14, 15, 16, 17, 19, 21, 22, 23, 28, 30, 32, 33,
    43, 54, 56, 59, 71, 72,
})


class RestrictedSpirvProgram:
    """Small single-function SSA interpreter for validated immutable modules."""
    def __init__(self, *, raw, stage, instructions, decorations, builtins,
                 types, pointers, variables, constants, steps, validator):
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.stage = stage
        self.instructions = tuple(instructions)
        self.decorations = dict(decorations)
        self.builtins = frozenset(builtins)
        self.types = dict(types)
        self.pointers = dict(pointers)
        self.variables = dict(variables)
        self.constants = dict(constants)
        self.steps = tuple(steps)
        self.validator = validator
        self.execution_calls = 0

    @classmethod
    def from_file(cls, path):
        path = Path(path).resolve(strict=True)
        validation = validate_module(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != validation["sha256"]:
            raise RuntimeError("SPIRV_SOURCE_CHANGED_AFTER_REAL_VALIDATION")
        obj = cls._parse_validated_bytes(raw)
        obj.validator = validation["spirv_val"]
        return obj

    @classmethod
    def _parse_validated_bytes(cls, raw):
        """Internal structural parser; never use as the production validator."""
        if type(raw) is not bytes or not 24 <= len(raw) <= 1024 * 1024 or len(raw) % 4:
            raise UnsupportedSpirv("SPIRV_MODULE_SIZE")
        words = struct.unpack("<" + "I" * (len(raw) // 4), raw)
        if (words[0] != 0x07230203 or words[1] > 0x00010600 or
                words[1] < 0x00010000 or words[4] or words[3] > 10000):
            raise UnsupportedSpirv("SPIRV_MODULE_HEADER")
        offset, instructions = 5, []
        while offset < len(words):
            word = words[offset]
            count, opcode = word >> 16, word & 65535
            if opcode not in _ALLOWED:
                raise UnsupportedSpirv("SPIRV_OPCODE_UNSUPPORTED:" + str(opcode))
            if count < 1 or offset + count > len(words):
                raise UnsupportedSpirv("SPIRV_INSTRUCTION_LENGTH")
            instructions.append((opcode, tuple(words[offset + 1:offset + count])))
            offset += count
        if len(instructions) > 5000:
            raise UnsupportedSpirv("SPIRV_INSTRUCTION_BUDGET")
        stage, decorations, builtins = None, {}, set()
        types, pointers, variables, constants, steps = {}, {}, {}, {}, []
        function_count, return_count, in_function, entrypoints = 0, 0, False, 0
        for opcode, args in instructions:
            if opcode == 15:
                entrypoints += 1
                if len(args) < 3 or args[0] not in (0, 4):
                    raise UnsupportedSpirv("SPIRV_STAGE")
                stage = {0: "vertex", 4: "fragment"}[args[0]]
            elif opcode == 71 and len(args) >= 3 and args[1] == 30:
                decorations[args[0]] = args[2]
            elif opcode == 72 and len(args) >= 4 and args[2:4] == (11, 0):
                builtins.add((args[0], args[1]))
            elif opcode in (21, 22, 23, 28, 30):
                if not args:
                    raise UnsupportedSpirv("SPIRV_TYPE_INVALID")
                types[args[0]] = (opcode, args[1:])
                if opcode == 22 and args[1:] != (32,):
                    raise UnsupportedSpirv("SPIRV_FLOAT32_ONLY")
                if opcode == 21 and (len(args) != 3 or args[1] != 32):
                    raise UnsupportedSpirv("SPIRV_INT32_ONLY")
                if opcode == 23 and (len(args) != 3 or args[2] not in (2, 3, 4)):
                    raise UnsupportedSpirv("SPIRV_VECTOR_PROFILE")
            elif opcode == 32:
                if len(args) != 3:
                    raise UnsupportedSpirv("SPIRV_POINTER_TYPE")
                pointers[args[0]] = (args[1], args[2])
            elif opcode == 43:
                if len(args) != 3 or args[0] not in types:
                    raise UnsupportedSpirv("SPIRV_CONSTANT_TYPE")
                scalar, spec = types[args[0]]
                if scalar == 22:
                    value = struct.unpack("<f", struct.pack("<I", args[2]))[0]
                elif scalar == 21:
                    value = args[2]
                else:
                    raise UnsupportedSpirv("SPIRV_CONSTANT_UNSUPPORTED")
                constants[args[1]] = value
            elif opcode == 59:
                if len(args) != 3 or args[0] not in pointers or args[2] not in (1, 3):
                    raise UnsupportedSpirv("SPIRV_VARIABLE_STORAGE")
                variables[args[1]] = (args[0], args[2])
            elif opcode == 54:
                function_count += 1
                in_function = True
            if in_function and opcode not in _METADATA:
                steps.append((opcode, args))
                if opcode == 253:
                    return_count += 1
        if (entrypoints != 1 or function_count != 1 or return_count != 1 or
                not steps or steps[-1][0] != 56):
            raise UnsupportedSpirv("SPIRV_SINGLE_STRAIGHTLINE_FUNCTION_REQUIRED")
        if not {14, 15, 17, 54, 56, 253}.issubset(
                opcode for opcode, _ in instructions):
            raise UnsupportedSpirv("SPIRV_INCOMPLETE_MODULE")
        return cls(raw=raw, stage=stage, instructions=instructions,
                   decorations=decorations, builtins=builtins, types=types,
                   pointers=pointers, variables=variables, constants=constants,
                   steps=steps, validator={"executed": False})

    def invoke(self, location_inputs):
        """Evaluate original SPIR-V instructions, never precomputed colors."""
        if not isinstance(location_inputs, dict):
            raise UnsupportedSpirv("SPIRV_INPUTS")
        values, aliases, stores = dict(self.constants), {}, {}
        def pointer(ident):
            if ident in aliases:
                return aliases[ident]
            if ident in self.variables:
                return (ident, ())
            raise UnsupportedSpirv("SPIRV_POINTER_UNKNOWN")

        def read(ident):
            root, indices = pointer(ident)
            if root in self.decorations and self.variables[root][1] == 1:
                loc = self.decorations[root]
                if loc not in location_inputs:
                    raise UnsupportedSpirv("SPIRV_INPUT_LOCATION_MISSING")
                result = location_inputs[loc]
            elif (root, ()) in stores:
                result = stores[(root, ())]
            elif (root, indices) in stores:
                return stores[(root, indices)]
            else:
                raise UnsupportedSpirv("SPIRV_UNINITIALIZED_LOAD")
            try:
                for index in indices:
                    result = result[index]
            except (IndexError, KeyError, TypeError) as exc:
                raise UnsupportedSpirv("SPIRV_ACCESS_CHAIN_BOUNDS") from exc
            return result

        returned = False
        for opcode, args in self.steps:
            if opcode in (248, 56):
                continue
            if opcode == 253:
                returned = True
                break
            if opcode == 61:
                values[args[1]] = read(args[2])
            elif opcode == 81:
                result = values[args[2]]
                for index in args[3:]:
                    result = result[index]
                values[args[1]] = result
            elif opcode == 80:
                values[args[1]] = tuple(values[part] for part in args[2:])
            elif opcode == 65:
                root, indices = pointer(args[2])
                new_indices = tuple(int(values[index]) for index in args[3:])
                if any(x < 0 or x > 16 for x in new_indices):
                    raise UnsupportedSpirv("SPIRV_ACCESS_CHAIN_BOUNDS")
                aliases[args[1]] = (root, indices + new_indices)
            elif opcode == 62:
                root, indices = pointer(args[0])
                if self.variables[root][1] != 3:
                    raise UnsupportedSpirv("SPIRV_STORE_NONOUTPUT")
                stores[(root, indices)] = values[args[1]]
            else:
                raise UnsupportedSpirv("SPIRV_RUNTIME_OPCODE_UNSUPPORTED:" + str(opcode))
        if not returned:
            raise UnsupportedSpirv("SPIRV_NO_RETURN")
        outputs = {}
        for root, (ptr_type, storage) in self.variables.items():
            if storage != 3:
                continue
            if root in self.decorations:
                key = ("location", self.decorations[root])
                value = stores.get((root, ()))
            else:
                pointee_type = self.pointers[ptr_type][1]
                key = ("builtin", 0) if (pointee_type, 0) in self.builtins else None
                value = stores.get((root, (0,)))
            if key is not None:
                if value is None:
                    raise UnsupportedSpirv("SPIRV_OUTPUT_NOT_WRITTEN")
                outputs[key] = value
        expected = {("builtin", 0), ("location", 0)} if self.stage == "vertex" else {("location", 0)}
        if set(outputs) != expected:
            raise UnsupportedSpirv("SPIRV_OUTPUT_PROFILE")
        self.execution_calls += 1
        return outputs


class RestrictedSpirvColorShader(Shader):
    """Opt-in Python CPU tile shader, executes *validated* SPIR-V operations."""
    def __init__(self, vertex: RestrictedSpirvProgram, fragment: RestrictedSpirvProgram):
        if (type(vertex) is not RestrictedSpirvProgram or
                type(fragment) is not RestrictedSpirvProgram or
                vertex.stage != "vertex" or fragment.stage != "fragment" or
                vertex.validator.get("executed") is not True or
                fragment.validator.get("executed") is not True):
            raise UnsupportedSpirv("SPIRV_VALIDATION_REQUIRED")
        self.vertex = vertex
        self.fragment = fragment

    def vertex_shader(self, vertex):
        outputs = self.vertex.invoke({
            0: tuple(np.asarray(vertex.position[:3], dtype=np.float32)),
            1: tuple(np.asarray(vertex.color, dtype=np.float32)),
        })
        position = np.asarray(outputs[("builtin", 0)], dtype=np.float32)
        color = np.asarray(outputs[("location", 0)], dtype=np.float32)
        if position.shape != (4,) or color.shape != (3,) or not np.isfinite(position).all():
            raise UnsupportedSpirv("SPIRV_VERTEX_OUTPUT_SHAPE")
        return position, {"color": color}

    def fragment_shader(self, varyings):
        color = np.asarray(varyings["color"], dtype=np.float32)
        if color.shape != (3,) or not np.isfinite(color).all():
            raise UnsupportedSpirv("SPIRV_FRAGMENT_INPUT_SHAPE")
        outputs = self.fragment.invoke({0: tuple(color)})
        vec = np.asarray(outputs[("location", 0)], dtype=np.float32)
        if vec.shape != (4,) or not np.isfinite(vec).all():
            raise UnsupportedSpirv("SPIRV_FRAGMENT_OUTPUT_SHAPE")
        scaled = np.clip(vec * np.float32(255.0), 0, 255).astype(np.uint8)
        return tuple(int(x) for x in scaled)
