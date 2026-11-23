"""Exact-revision real native C++17 command replay receipt. NOT Vulkan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.drivers.command_submission import record_native_draws, submit_native_draws
from software_gpu.drivers.native_bridge import AREDriverBridge, build_driver_bridge
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.geometry import prepare_triangles
from software_gpu.graphics.native_raster import pack_triangles


def verify(revision: str) -> dict:
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if not revision or source != revision:
        raise RuntimeError("ARE_COMMAND_REVISION_MISMATCH")
    with tempfile.TemporaryDirectory(prefix="are-native-command-") as workspace:
        binary, build = build_driver_bridge(Path(workspace) / "driver")
        bridge = AREDriverBridge(binary, build["binary_sha256"])
        mesh, faces = make_fixture(4, 0.8)
        triangles = prepare_triangles(mesh, faces, VertexColorShader(), 32, 24)
        if not triangles:
            raise RuntimeError("ARE_COMMAND_NO_ACTUAL_TRIANGLES")
        packed = pack_triangles(triangles)
        packet = record_native_draws([packed, packed])
        def fresh():
            fb = Framebuffer(32, 24)
            fb.clear()
            return fb
        observed, direct, replay = fresh(), fresh(), fresh()
        outcome = submit_native_draws(bridge, observed, packet)
        direct_first = bridge.draw_packed(direct, packed)
        direct_second = bridge.draw_packed(direct, packed)
        repeated = submit_native_draws(bridge, replay, packet)
        if (outcome["shaded_samples"] <= 0 or
                outcome["shaded_samples"] != direct_first["shaded_samples"] + direct_second["shaded_samples"] or
                observed.color_buffer.tobytes() != direct.color_buffer.tobytes() or
                observed.depth_buffer.tobytes() != direct.depth_buffer.tobytes() or
                observed.color_buffer.tobytes() != replay.color_buffer.tobytes() or
                observed.depth_buffer.tobytes() != replay.depth_buffer.tobytes() or
                outcome["rgba_sha256"] != repeated["rgba_sha256"] or
                outcome["depth_sha256"] != repeated["depth_sha256"]):
            raise RuntimeError("ARE_COMMAND_REAL_NATIVE_PARITY_FAILED")
        record = {
            "protocol": "are.native-command-evidence.v1",
            "status": "PASS_REAL_NATIVE_CPU_ONLY",
            "source_revision": source,
            "driver_binary_sha256": build["binary_sha256"],
            "driver_source_sha256": build["source_sha256"],
            "packet_sha256": packet.command_sha256,
            "submitted_draws": outcome["submitted_draws"],
            "shaded_samples": outcome["shaded_samples"],
            "rgba_sha256": outcome["rgba_sha256"],
            "depth_sha256": outcome["depth_sha256"],
            "direct_parity": True,
            "native_replay": True,
            "vulkan_icd": False,
            "vulkan_command_buffer": False,
            "unity_runtime_test": "NOT_RUN",
        }
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    record["receipt_sha256"] = hashlib.sha256(canonical).hexdigest()
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = verify(args.expected_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("ARE_COMMAND_REAL_NATIVE_CPU_ONLY_PASS " + report["receipt_sha256"])


if __name__ == "__main__":
    main()
