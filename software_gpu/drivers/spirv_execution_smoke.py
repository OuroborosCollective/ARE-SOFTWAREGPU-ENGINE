"""Real SPIR-V bytecode execution on an opt-in ARE Python tile renderer.

This executes the vertex/fragment operations compiled by real glslang and
validated by real SPIRV-Tools. It is *not* a Vulkan ICD, NIR, Unity renderer,
or native C++ shader backend. No system driver or simulation tick is touched.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

from software_gpu.drivers.spirv_opcode_executor import (
    RestrictedSpirvProgram, RestrictedSpirvColorShader,
)
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Vertex


def execute(vertex_path: Path, fragment_path: Path, expected_revision: str) -> dict:
    actual_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip()
    if expected_revision != actual_revision:
        raise RuntimeError("SPIRV_EXEC_REVISION_MISMATCH")
    v = RestrictedSpirvProgram.from_file(vertex_path)
    f = RestrictedSpirvProgram.from_file(fragment_path)
    shader = RestrictedSpirvColorShader(v, f)
    mesh = [
        Vertex(np.array([-0.8, -0.8, 0, 1], np.float32),
               color=np.array([1, 0, 0], np.float32)),
        Vertex(np.array([-0.8, 0.8, 0, 1], np.float32),
               color=np.array([1, 0, 0], np.float32)),
        Vertex(np.array([0.8, 0.8, 0, 1], np.float32),
               color=np.array([1, 0, 0], np.float32)),
        Vertex(np.array([0.8, -0.8, 0, 1], np.float32),
               color=np.array([1, 0, 0], np.float32)),
    ]
    indices = [(0, 2, 1), (0, 3, 2)]
    def render(used_shader):
        fb = Framebuffer(32, 24)
        fb.clear()
        renderer = SoftwareRasterizer(fb, backend="tiles", num_threads=1)
        try:
            renderer.draw_mesh(mesh, indices, used_shader)
        finally:
            renderer.executor.shutdown()
        return fb

    actual = render(shader)
    baseline = render(VertexColorShader())
    if not (np.array_equal(actual.color_buffer, baseline.color_buffer) and
            np.array_equal(actual.depth_buffer, baseline.depth_buffer)):
        raise RuntimeError("SPIRV_EXEC_REAL_FRAME_PARITY_FAILED")
    if v.execution_calls != len(mesh) or f.execution_calls <= 0:
        raise RuntimeError("SPIRV_EXEC_BYTECODE_NOT_INVOKED")
    if not np.any(actual.depth_buffer < np.float32(1.0)):
        raise RuntimeError("SPIRV_EXEC_NO_VISIBLE_PIXELS")
    # A second fresh program instance must replay identical actual output.
    repeat_program = RestrictedSpirvColorShader(
        RestrictedSpirvProgram.from_file(vertex_path),
        RestrictedSpirvProgram.from_file(fragment_path),
    )
    replay = render(repeat_program)
    if (replay.color_buffer.tobytes() != actual.color_buffer.tobytes() or
            replay.depth_buffer.tobytes() != actual.depth_buffer.tobytes()):
        raise RuntimeError("SPIRV_EXEC_REPLAY_MISMATCH")

    receipt = {
        "protocol": "are.spirv-restricted-tiles-execution.v1",
        "status": "REAL_RESTRICTED_SSA_EXECUTION",
        "revision": actual_revision,
        "vertex_sha256": v.sha256,
        "fragment_sha256": f.sha256,
        "vertex_bytecode_execution_calls": v.execution_calls,
        "fragment_bytecode_execution_calls": f.execution_calls,
        "shaded_pixels_nonempty": int(np.count_nonzero(actual.depth_buffer < 1.0)),
        "rgba_sha256": hashlib.sha256(actual.color_buffer.tobytes()).hexdigest(),
        "depth_sha256": hashlib.sha256(actual.depth_buffer.tobytes()).hexdigest(),
        "reference_renderer": "existing ARE Python tiles VertexColorShader",
        "full_rgba_and_depth_equal": True,
        "replay_byte_equal": True,
        "spv_validation": "real SPIRV-Tools spirv-val",
        "shader_backend": "opt-in restricted Python SSA interpreter",
        "native_cpp_spirv_shader_execution": False,
        "vulkan_icd_exposed": False,
        "vulkan_device_enumerated_as_are": False,
        "unity_runtime_verified": False,
    }
    body = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["receipt_sha256"] = hashlib.sha256(body).hexdigest()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vertex", type=Path, required=True)
    parser.add_argument("--fragment", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = execute(args.vertex, args.fragment, args.expected_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("SPIRV_RESTRICTED_REAL_TILE_EXECUTION_PASS " + receipt["receipt_sha256"])


if __name__ == "__main__":
    main()
