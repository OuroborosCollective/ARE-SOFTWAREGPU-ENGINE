"""Read real SPIR-V modules and require spirv-val before admission.

Source intake only. There is no ARE SPIR-V compiler, GPU API object,
pipeline, shader execution, or Vulkan ICD behind this boundary.
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
_STAGES = {0: "vertex", 4: "fragment"}
_ALLOWED_CAPABILITIES = {1}  # SPIR-V Shader; extra capabilities must be reviewed first
_MAX_MODULE_BYTES = 1024 * 1024
_MAX_BOUND = 1048576


def _entry_name(words: tuple[int, ...]) -> str:
    raw = struct.pack("<" + "I" * len(words), *words)
    split = raw.find(b"\0")
    if split < 1 or raw[split + 1:(split + 4) // 4 * 4].strip(b"\0"):
        raise ValueError("ARE_SPIRV_ENTRY_NAME")
    try:
        value = raw[:split].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("ARE_SPIRV_ENTRY_UTF8") from exc
    if not value or len(value) > 128 or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value):
        raise ValueError("ARE_SPIRV_ENTRY_IDENTIFIER")
    return value


def parse_spirv_module(binary: bytes) -> dict:
    """Inspect bounded structural identity, not complete SPIR-V semantic validity."""
    if type(binary) is not bytes or len(binary) < 20 or len(binary) % 4 or len(binary) > _MAX_MODULE_BYTES:
        raise ValueError("ARE_SPIRV_MODULE_SIZE")
    words = struct.unpack("<" + "I" * (len(binary) // 4), binary)
    magic, version, generator, bound, schema = words[:5]
    if magic != _MAGIC or schema != 0 or not (0 < bound <= _MAX_BOUND):
        raise ValueError("ARE_SPIRV_HEADER")
    if (version >> 16) != 1 or (version & 0xFF) != 0 or ((version >> 8) & 0xFF) > 6:
        raise ValueError("ARE_SPIRV_VERSION")
    offset = 5
    capabilities: list[int] = []
    entry_points: list[tuple[int, int, str]] = []
    memory_count = 0
    opcodes: set[int] = set()
    while offset < len(words):
        prefix = words[offset]
        word_count, opcode = prefix >> 16, prefix & 0xFFFF
        if word_count == 0 or offset + word_count > len(words):
            raise ValueError("ARE_SPIRV_INSTRUCTION_BOUNDS")
        inst = words[offset + 1:offset + word_count]
        opcodes.add(opcode)
        if opcode == 17:
            if word_count != 2 or inst[0] not in _ALLOWED_CAPABILITIES:
                raise ValueError("ARE_SPIRV_CAPABILITY_UNSUPPORTED")
            capabilities.append(inst[0])
        elif opcode == 14:
            if word_count != 3 or inst[0] not in (0, 1, 2) or inst[1] not in (1, 2, 3):
                raise ValueError("ARE_SPIRV_MEMORY_MODEL_UNSUPPORTED")
            memory_count += 1
        elif opcode == 15:
            if word_count < 4 or inst[0] not in _STAGES or not (0 < inst[1] < bound):
                raise ValueError("ARE_SPIRV_STAGE_UNSUPPORTED")
            # Entry point names may be followed by interface IDs: parse words only
            # until the first null-terminated 32-bit word.
            name_words = []
            for value in inst[2:]:
                name_words.append(value)
                if 0 in struct.pack("<I", value):
                    break
            else:
                raise ValueError("ARE_SPIRV_ENTRY_NAME")
            name = _entry_name(tuple(name_words))
            interface_ids = inst[2 + len(name_words):]
            if any(not 0 < identifier < bound for identifier in interface_ids):
                raise ValueError("ARE_SPIRV_ENTRY_INTERFACE")
            entry_points.append((inst[0], inst[1], name))
        offset += word_count
    if (not capabilities or memory_count != 1 or not entry_points or
            len(entry_points) != len(set(entry_points))):
        raise ValueError("ARE_SPIRV_REQUIRED_DECLARATIONS")
    return {
        "protocol": "are.spirv-source-inspection.v1",
        "module_sha256": hashlib.sha256(binary).hexdigest(),
        "size_bytes": len(binary),
        "spirv_version": f"1.{(version >> 8) & 0xFF}",
        "generator_id": generator,
        "id_bound": bound,
        "stages": sorted(set(_STAGES[stage] for stage, _, _ in entry_points)),
        "entry_points": [{"stage": _STAGES[s], "id": i, "name": n}
                         for s, i, n in entry_points],
        "capabilities": sorted(set(capabilities)),
        "opcodes_observed": sorted(opcodes),
        "spirv_validation_executed": False,
        "are_shader_executed": False,
        "are_vkphysicaldevice_exposed": False,
    }


def validate_spirv_module(path: Path, *, validator: str = "spirv-val") -> dict:
    """Requires actual Khronos SPIRV-Tools validator execution on exact file bytes."""
    source = Path(path).resolve(strict=True)
    binary = source.read_bytes()
    inspection = parse_spirv_module(binary)
    result = subprocess.run([validator, "--target-env", "vulkan1.1", str(source)],
                            capture_output=True, text=True, timeout=40, check=False)
    if result.returncode:
        raise ValueError("ARE_SPIRV_VALIDATOR_REJECTED:" + result.stderr[-600:])
    if hashlib.sha256(source.read_bytes()).hexdigest() != inspection["module_sha256"]:
        raise ValueError("ARE_SPIRV_CHANGED_DURING_VALIDATION")
    version = subprocess.run([validator, "--version"], capture_output=True, text=True,
                             timeout=15, check=True)
    inspection["spirv_validation_executed"] = True
    inspection["spirv_validator"] = version.stdout.strip()[:1024]
    inspection["validator_stdout_sha256"] = hashlib.sha256(result.stdout.encode()).hexdigest()
    inspection["validator_stderr_sha256"] = hashlib.sha256(result.stderr.encode()).hexdigest()
    inspection["status"] = "SPIRV_TOOLS_VALIDATED_SOURCE_ONLY"
    canonical = json.dumps(inspection, sort_keys=True, separators=(",", ":")).encode()
    inspection["receipt_sha256"] = hashlib.sha256(canonical).hexdigest()
    return inspection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--expected-stage", choices=("vertex", "fragment"), required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("Full source revision required")
    evidence = validate_spirv_module(args.module)
    if evidence["stages"] != [args.expected_stage]:
        raise ValueError("ARE_SPIRV_STAGE_MISMATCH")
    evidence["repo_revision"] = args.source_revision
    evidence["receipt_sha256"] = hashlib.sha256(json.dumps(
        {k: v for k, v in evidence.items() if k != "receipt_sha256"},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("ARE_SPIRV_SOURCE_VALIDATED_NOT_EXECUTED " + evidence["receipt_sha256"])


if __name__ == "__main__":
    main()
