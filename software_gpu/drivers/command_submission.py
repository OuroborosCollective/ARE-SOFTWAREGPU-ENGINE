"""Deterministic CPU command recording -> real ARE native raster submission.

API-neutral research seam for later Vulkan command/queue integration. Commands
contain frozen ordered *bytes*, not borrowed NumPy pointers, so recording is
independent of caller mutations. Submission rasterizes to isolated real ARE
RGBA8/Float32 buffers and commits them only if every draw succeeds.
No Vulkan command buffers, VkQueueSubmit, SPIR-V execution or WSI are exposed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np

from software_gpu.drivers.native_bridge import AREDriverBridge
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.learning import bucket, configured_learner, implementation_id, scope_key

_STRIDE = 23
_MAX_COMMANDS = 256
_MAX_TRIANGLES = 200_000
_MAX_PAYLOAD = _MAX_TRIANGLES * _STRIDE * 8
_MAX_SAMPLES = 64_000_000


def _digest(rows: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


@dataclass(frozen=True)
class NativeRecordedDraw:
    payload: bytes
    count: int
    sha256: str


@dataclass(frozen=True)
class NativeCommandPacket:
    protocol: str
    profile: str
    commands: tuple[NativeRecordedDraw, ...]
    command_sha256: str


def record_native_draws(draws, *, profile: str = "packed-vertex-color") -> NativeCommandPacket:
    """Freeze a bounded ordered draw sequence, without rendering or time sources."""
    if profile != "packed-vertex-color":
        raise ValueError("ARE_COMMAND_PROFILE")
    if not isinstance(draws, (list, tuple)) or not 1 <= len(draws) <= _MAX_COMMANDS:
        raise ValueError("ARE_COMMAND_BUDGET")
    records: list[NativeRecordedDraw] = []
    total = 0
    for source in draws:
        if (type(source) is not np.ndarray or
                source.dtype != np.dtype("float64") or
                source.ndim != 2 or source.shape[1] != _STRIDE or
                not source.flags.c_contiguous or not source.flags.aligned):
            raise ValueError("ARE_COMMAND_PACKED")
        n = source.shape[0]
        total += n
        if n > _MAX_TRIANGLES or total > _MAX_TRIANGLES or source.nbytes > _MAX_PAYLOAD:
            raise ValueError("ARE_COMMAND_BUDGET")
        frozen = source.tobytes(order="C")
        records.append(NativeRecordedDraw(frozen, n, hashlib.sha256(frozen).hexdigest()))
    digests = [{"count": r.count, "sha256": r.sha256} for r in records]
    return NativeCommandPacket("are.native-command-packet.v1", profile, tuple(records),
                               _digest(digests))


def _validate_frame(framebuffer: Framebuffer) -> None:
    if (type(framebuffer) is not Framebuffer or
            not isinstance(framebuffer.width, int) or not isinstance(framebuffer.height, int) or
            not 1 <= framebuffer.width <= 4096 or
            not 1 <= framebuffer.height <= 4096 or
            framebuffer.width * framebuffer.height > 4194304):
        raise ValueError("ARE_COMMAND_FRAME")
    width, height = framebuffer.width, framebuffer.height
    for array, dtype, shape in (
        (framebuffer.color_buffer, np.dtype("uint8"), (height, width, 4)),
        (framebuffer.depth_buffer, np.dtype("float32"), (height, width)),
    ):
        if (type(array) is not np.ndarray or array.dtype != dtype or
                array.shape != shape or not array.flags.c_contiguous or
                not array.flags.aligned or not array.flags.writeable):
            raise ValueError("ARE_COMMAND_FRAME")
    if np.shares_memory(framebuffer.color_buffer, framebuffer.depth_buffer):
        raise ValueError("ARE_COMMAND_FRAME")


def submit_native_draws(bridge: AREDriverBridge, framebuffer: Framebuffer,
                        packet: NativeCommandPacket, *, _icd_pipeline=None) -> dict:
    """Run actual C++17 draws in order and commit all output or none.

    Caller exclusively owns the framebuffer and the bridge for this synchronous
    call; no speculative concurrency or simulation/gameplay authority.
    """
    if type(bridge) is not AREDriverBridge:
        raise ValueError("ARE_COMMAND_BRIDGE")
    _validate_frame(framebuffer)
    if (type(packet) is not NativeCommandPacket or
            packet.protocol != "are.native-command-packet.v1" or
            packet.profile != "packed-vertex-color" or
            not 1 <= len(packet.commands) <= _MAX_COMMANDS):
        raise ValueError("ARE_COMMAND_PROFILE")
    rows = []
    total = 0
    for command in packet.commands:
        if type(command) is not NativeRecordedDraw or type(command.payload) is not bytes:
            raise ValueError("ARE_COMMAND_PAYLOAD")
        if (type(command.count) is not int or not 0 <= command.count <= _MAX_TRIANGLES or
                len(command.payload) != command.count * _STRIDE * 8 or
                hashlib.sha256(command.payload).hexdigest() != command.sha256):
            raise ValueError("ARE_COMMAND_PAYLOAD_DIGEST")
        total += command.count
        if total > _MAX_TRIANGLES:
            raise ValueError("ARE_COMMAND_BUDGET")
        rows.append({"count": command.count, "sha256": command.sha256})
    if _digest(rows) != packet.command_sha256:
        raise ValueError("ARE_COMMAND_PACKET_DIGEST")
    if total * framebuffer.width * framebuffer.height > _MAX_SAMPLES:
        raise ValueError("ARE_COMMAND_BUDGET")

    # Both paths below start from EXACTLY the same color/depth snapshot.
    # Never learn from a failed reference. Never mutate the caller's image
    # before every native C++ draw has completed on its private framebuffer.
    def execute(alternative):
        stage = Framebuffer(framebuffer.width, framebuffer.height)
        stage.color_buffer[:] = framebuffer.color_buffer
        stage.depth_buffer[:] = framebuffer.depth_buffer
        counts = {"candidate_samples": 0, "covered_samples": 0, "shaded_samples": 0}
        native_calls = 0
        if alternative and len(packet.commands) > 1:
            # Candidate is real C++ raster over precisely the same ordered
            # triangles; collapse only the draw-call boundary, not geometry
            # order, blending, depth, clipping or the shader implementation.
            data = np.concatenate([
                np.frombuffer(c.payload, dtype="<f8").reshape((c.count, _STRIDE))
                for c in packet.commands
            ], axis=0)
            try:
                result = bridge.draw_packed(stage, data)
            except ValueError as exc:
                raise ValueError("ARE_COMMAND_SUBMISSION_REJECTED:" + str(exc)) from exc
            native_calls = 1
            for name in counts:
                counts[name] = result[name]
        else:
            for command in packet.commands:
                data = np.frombuffer(command.payload, dtype="<f8").copy().reshape(
                    (command.count, _STRIDE)
                )
                try:
                    result = bridge.draw_packed(stage, data)
                except ValueError as exc:
                    raise ValueError("ARE_COMMAND_SUBMISSION_REJECTED:" + str(exc)) from exc
                native_calls += 1
                for name in counts:
                    counts[name] += result[name]
        return stage, counts, native_calls

    def fingerprint(result):
        stage, counts, _calls = result
        digest = hashlib.sha256()
        digest.update(stage.color_buffer.tobytes())
        digest.update(stage.depth_buffer.tobytes())
        for name in ("candidate_samples", "covered_samples", "shaded_samples"):
            digest.update(int(counts[name]).to_bytes(8, byteorder="little", signed=False))
        return digest.hexdigest()

    def publish(result):
        stage, _counts, _calls = result
        # Preserve references to pre-existing caller arrays.
        np.copyto(framebuffer.color_buffer, stage.color_buffer)
        np.copyto(framebuffer.depth_buffer, stage.depth_buffer)

    learner = configured_learner()
    learning_receipt = None
    if learner is None:
        result = execute(False)
        publish(result)
    else:
        root = Path(__file__).resolve().parents[2]
        implementation = implementation_id(
            __file__, Path(__file__).with_name("native_bridge.py"),
            root / "native/raster/core.hpp",
            root / "native/raster/driver_adapter.hpp",
            root / "native/raster/driver_adapter.cpp",
        )
        state_hash = hashlib.sha256()
        state_hash.update(framebuffer.color_buffer.tobytes())
        state_hash.update(framebuffer.depth_buffer.tobytes())
        key = scope_key(
            stage="native-command-cpp17" if _icd_pipeline is None else "vulkan-queue-cpp17",
            **({"pipeline_sha256": _icd_pipeline} if _icd_pipeline is not None else {}),
            variant="collapsed-native-draw-v1" if len(packet.commands) > 1 else None,
            implementation=implementation,
            native_binary_sha256=bridge.binary_sha256,
            numpy=np.__version__,
            width=bucket(framebuffer.width),
            height=bucket(framebuffer.height),
            triangle_total=bucket(total),
            packet_sha256=packet.command_sha256,
            initial_frame_sha256=state_hash.hexdigest(),
        )
        # Single-draw packets have no meaningful different C++ strategy.
        # They still contribute *observational* timing weights in the same DB.
        result, learning_receipt = learner.execute(
            key, execute, fingerprint if len(packet.commands) > 1 else None, publish
        )

    _stage, counts, calls = result
    return {
        "protocol": "are.native-command-submission.v1",
        "renderer": "real native ARE CPU C++17",
        "native_binary_sha256": bridge.binary_sha256,
        "packet_sha256": packet.command_sha256,
        "submitted_draws": len(packet.commands),
        "native_cpp_calls": calls,
        "learning": learning_receipt,
        **counts,
        "rgba_sha256": hashlib.sha256(framebuffer.color_buffer.tobytes()).hexdigest(),
        "depth_sha256": hashlib.sha256(framebuffer.depth_buffer.tobytes()).hexdigest(),
        "vulkan_command_buffer": False,
        "vulkan_icd": False,
        "spirv_native_cpp_execution": False,
        "unity_runtime": False,
    }
