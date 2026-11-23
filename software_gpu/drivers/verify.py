"""Evidence from real native CPU frame execution; never claims a Vulkan ICD."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.geometry import prepare_triangles
from software_gpu.graphics.native_raster import (
    NativeRasterKernel, build_raster_kernel, pack_triangles,
)
from software_gpu.drivers.native_bridge import AREDriverBridge, build_driver_bridge


def verify(expected_revision: str) -> dict:
    repo = Path(__file__).resolve().parents[2]
    revision = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if expected_revision and revision != expected_revision:
        raise RuntimeError("ARE_DRIVER_REVISION_MISMATCH")
    with tempfile.TemporaryDirectory(prefix="are-driver-evidence-", ignore_cleanup_errors=True) as directory:
        driver_binary, driver_build = build_driver_bridge(Path(directory) / "driver")
        native_binary, native_build = build_raster_kernel(Path(directory) / "reference")
        bridge = AREDriverBridge(driver_binary, driver_build["binary_sha256"])
        raster = NativeRasterKernel(native_binary, native_build["binary_sha256"])
        mesh, faces = make_fixture(4, 0.8)
        shader = VertexColorShader()
        triangles = prepare_triangles(mesh, faces, shader, 32, 24)
        if not triangles:
            raise RuntimeError("ARE_DRIVER_EMPTY_REAL_DRAW")
        packed = pack_triangles(triangles)
        target, reference, replay = (Framebuffer(32, 24) for _ in range(3))
        for fb in (target, reference, replay):
            fb.clear()
        result = bridge.draw_packed(target, packed)
        native = raster.draw(reference, triangles, shader)
        again = bridge.draw_packed(replay, packed)
        if (result["shaded_samples"] <= 0 or
                result["shaded_samples"] != native["shaded_samples"] or
                target.color_buffer.tobytes() != reference.color_buffer.tobytes() or
                target.depth_buffer.tobytes() != reference.depth_buffer.tobytes() or
                result["rgba_sha256"] != again["rgba_sha256"] or
                result["depth_sha256"] != again["depth_sha256"]):
            raise RuntimeError("ARE_DRIVER_REAL_FRAME_PARITY")
        caps = bridge.capabilities
        if (caps.abi_version != 1 or caps.device_kind != 1 or
                caps.profile_bits != 1 or caps.supports_spirv or
                caps.supports_vulkan_icd or caps.supports_wsi):
            raise RuntimeError("ARE_DRIVER_UNPROVEN_CAPABILITIES")
        data = {
            "protocol": "are.driver-adapter-evidence.v1",
            "status": "PASS",
            "repo_revision": revision,
            "driver_binary_sha256": driver_build["binary_sha256"],
            "reference_binary_sha256": native_build["binary_sha256"],
            "driver_source_sha256": driver_build["source_sha256"],
            "driver_compiler": driver_build["compiler_version"],
            "driver_flags": driver_build["flags"],
            "renderer": result,
            "native_reference_shaded_samples": native["shaded_samples"],
            "repeat_rgba_sha256": again["rgba_sha256"],
            "repeat_depth_sha256": again["depth_sha256"],
            "vulkan_loader_test": "NOT_RUN",
            "unity_player_editor_test": "NOT_RUN",
            "open_gl_test": "NOT_RUN",
        }
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    data["receipt_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = verify(args.expected_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
    print("ARE_DRIVER_REAL_CPU_PASS " + receipt["repo_revision"] + " " + receipt["receipt_sha256"])


if __name__ == "__main__":
    main()
