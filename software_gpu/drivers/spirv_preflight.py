"""Bounded real SPIR-V validation and stage inspection, NOT ARE execution.

The Khronos SPIR-V Tools CLI is the validation authority. This module only
inspects physical words/entry points and ties the validated bytes to evidence.
It does not compile SPIR-V to ARE, execute a shader, or create a Vulkan device.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


_MAGIC = 0x07230203
_MAX_MODULE_BYTES = 4 * 1024 * 1024
_MAX_ID_BOUND = 1_000_000
_MODELS = {0: "vertex", 4: "fragment"}


def inspect_module(blob: bytes) -> dict:
    """Strict structure and declared entry-point scan, not semantic validation."""
    if type(blob) is not bytes or len(blob) < 24 or len(blob) > _MAX_MODULE_BYTES or len(blob) % 4:
        raise ValueError("SPIRV_SIZE_INVALID")
    words = struct.unpack("<" + "I" * (len(blob) // 4), blob)
    magic, version, generator, bound, reserved = words[:5]
    major, minor = (version >> 16) & 255, (version >> 8) & 255
    if (magic != _MAGIC or version & 0xFF00_00FF or major != 1 or minor > 6 or
            not 1 < bound <= _MAX_ID_BOUND or reserved):
        raise ValueError("SPIRV_HEADER_INVALID")
    offset, stages, opcodes = 5, [], set()
    while offset < len(words):
        first = words[offset]
        count, opcode = first >> 16, first & 0xFFFF
        if count < 1 or offset + count > len(words):
            raise ValueError("SPIRV_INSTRUCTION_LENGTH_INVALID")
        opcodes.add(opcode)
        if opcode == 15:  # OpEntryPoint: ExecutionModel, Id, null-terminated name, interface IDs
            if count < 4:
                raise ValueError("SPIRV_ENTRYPOINT_INVALID")
            model, identifier = words[offset + 1:offset + 3]
            name_bytes = blob[(offset + 3) * 4:(offset + count) * 4]
            nul = name_bytes.find(b"\0")
            if nul < 1 or nul > 256 or identifier == 0 or identifier >= bound:
                raise ValueError("SPIRV_ENTRYPOINT_INVALID")
            try:
                name = name_bytes[:nul].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("SPIRV_ENTRYPOINT_NAME_INVALID") from exc
            stages.append({"execution_model": model,
                           "stage": _MODELS.get(model, "unsupported"),
                           "name": name, "id": identifier})
        offset += count
    if len(stages) != 1 or stages[0]["stage"] == "unsupported":
        raise ValueError("SPIRV_STAGE_NOT_ADMITTED")
    # OpMemoryModel, OpCapability and OpEntryPoint must be in the original
    # module. Semantic correctness is proved separately by real spirv-val.
    if not {14, 15, 17}.issubset(opcodes):
        raise ValueError("SPIRV_REQUIRED_INSTRUCTIONS_MISSING")
    return {
        "protocol": "are.spirv-structure.v1",
        "spirv_version": f"{major}.{minor}",
        "words": len(words),
        "id_bound": bound,
        "entrypoint": stages[0],
        "opcodes_present": sorted(opcodes),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "is_are_executable": False,
    }


def validate_module(path: Path, *, validator: str = "spirv-val") -> dict:
    """Run authentic SPIRV-Tools validation; never substitute structural checks."""
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if not 24 <= size <= _MAX_MODULE_BYTES:
        raise ValueError("SPIRV_SIZE_INVALID")
    blob = path.read_bytes()
    structure = inspect_module(blob)
    command = [validator, "--target-env", "vulkan1.2", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ValueError("SPIRV_REAL_VALIDATOR_REJECTED:" + result.stderr[-1000:])
    # Bind the successful validation to the identical bytes; prevent
    # a local file replacement while the external validator runs.
    if hashlib.sha256(path.read_bytes()).hexdigest() != structure["sha256"]:
        raise RuntimeError("SPIRV_SOURCE_CHANGED_DURING_VALIDATION")
    structure["spirv_val"] = {
        "executed": True,
        "target_env": "vulkan1.2",
        "exit_code": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
    }
    structure["is_are_executable"] = False
    return structure


def make_receipt(modules: list[Path], *, revision: str, validator: str = "spirv-val") -> dict:
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("SPIRV_REVISION_REQUIRED")
    rows = [validate_module(path, validator=validator) for path in modules]
    stages = [x["entrypoint"]["stage"] for x in rows]
    if len(rows) != 2 or sorted(stages) != ["fragment", "vertex"]:
        raise ValueError("SPIRV_VERTEX_FRAGMENT_PAIR_REQUIRED")
    result = {
        "protocol": "are.spirv-preflight.v1",
        "status": "VALIDATED_INPUT_ONLY",
        "source_revision": revision,
        "modules": rows,
        "independent_validator": "SPIRV-Tools spirv-val",
        "are_shader_backend_executed": False,
        "are_vulkan_icd_present": False,
        "unity_verified": False,
        "next_required": "SPIR-V/NIR-to-ARE shader execution and Vk resource/queue binding",
    }
    digest_body = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["receipt_sha256"] = hashlib.sha256(digest_body).hexdigest()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vertex", type=Path, required=True)
    parser.add_argument("--fragment", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = make_receipt([args.vertex, args.fragment], revision=args.source_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("SPIRV_REAL_VALIDATOR_INPUT_ONLY_PASS " + receipt["receipt_sha256"])


if __name__ == "__main__":
    main()
