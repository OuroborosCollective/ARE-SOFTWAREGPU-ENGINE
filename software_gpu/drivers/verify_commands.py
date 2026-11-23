"""Exact-revision real native C++17 command replay receipt. NOT Vulkan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.drivers.command_submission import record_native_draws, submit_native_draws
from software_gpu.drivers.native_bridge import AREDriverBridge, build_driver_bridge
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.geometry import prepare_triangles
from software_gpu.graphics.native_raster import pack_triangles


def _check_revision(revision: str) -> None:
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if not revision or source != revision:
        raise RuntimeError("ARE_COMMAND_REVISION_MISMATCH")


def _verify_in_native_worker(revision: str, directory: Path) -> dict:
    """Render genuine ARE frames in the child, which owns the loaded DLL."""
    _check_revision(revision)
    binary, build = build_driver_bridge(directory / "driver")
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



def verify(revision: str) -> dict:
    """Verify real native rendering; clean up only after its DLL-owning child exits.

    Windows does not permit unlinking a ctypes-loaded DLL. A subprocess keeps
    temporary driver libraries alive until after its last real draw/receipt
    write, then exits before the parent tries to delete its workspace.
    This does not replace any renderer, native execution, or test with a fake.
    """
    _check_revision(revision)
    with tempfile.TemporaryDirectory(prefix="are-native-command-") as workspace:
        root = Path(workspace)
        result_path = root / "native-receipt.json"
        command = [
            sys.executable, "-m", "software_gpu.drivers.verify_commands",
            "--expected-revision", revision,
            "--output", str(result_path),
            "--native-worker-directory", str(root / "driver-work"),
        ]
        process = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if process.returncode:
            raise RuntimeError(
                "ARE_COMMAND_NATIVE_WORKER_FAILED:" + process.stderr[-4000:]
            )
        if not result_path.is_file():
            raise RuntimeError("ARE_COMMAND_NATIVE_WORKER_MISSING_RECEIPT")
        try:
            report = json.loads(result_path.read_text(encoding="utf-8"))
            claimed_sha = report.pop("receipt_sha256")
            actual_sha = hashlib.sha256(
                json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if (claimed_sha != actual_sha or
                    report["source_revision"] != revision or
                    report["protocol"] != "are.native-command-evidence.v1" or
                    report["status"] != "PASS_REAL_NATIVE_CPU_ONLY" or
                    report["submitted_draws"] != 2 or
                    report["shaded_samples"] <= 0 or
                    report["direct_parity"] is not True or
                    report["native_replay"] is not True or
                    report["vulkan_icd"] is not False or
                    report["vulkan_command_buffer"] is not False or
                    report["unity_runtime_test"] != "NOT_RUN"):
                raise ValueError("ARE_COMMAND_NATIVE_WORKER_INVALID_RECEIPT")
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("ARE_COMMAND_NATIVE_WORKER_INVALID_RECEIPT") from exc
        report["receipt_sha256"] = claimed_sha
        return report

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--native-worker-directory", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    report = (_verify_in_native_worker(args.expected_revision, args.native_worker_directory)
              if args.native_worker_directory is not None else verify(args.expected_revision))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("ARE_COMMAND_REAL_NATIVE_CPU_ONLY_PASS " + report["receipt_sha256"])


if __name__ == "__main__":
    main()
