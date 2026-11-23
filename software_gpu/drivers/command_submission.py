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

import numpy as np

from software_gpu.drivers.native_bridge import AREDriverBridge
from software_gpu.graphics.framebuffer import Framebuffer

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
                        packet: NativeCommandPacket) -> dict:
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

    # Keep original output unchanged even if the *last* real native draw fails.
    staging = Framebuffer(framebuffer.width, framebuffer.height)
    staging.color_buffer[:] = framebuffer.color_buffer
    staging.depth_buffer[:] = framebuffer.depth_buffer
    counts = {"candidate_samples": 0, "covered_samples": 0, "shaded_samples": 0}
    for command in packet.commands:
        data = np.frombuffer(command.payload, dtype="<f8").copy().reshape((command.count, _STRIDE))
        try:
            actual = bridge.draw_packed(staging, data)
        except ValueError as exc:
            raise ValueError("ARE_COMMAND_SUBMISSION_REJECTED:" + str(exc)) from exc
        for key in counts:
            counts[key] += actual[key]
    framebuffer.color_buffer[:] = staging.color_buffer
    framebuffer.depth_buffer[:] = staging.depth_buffer
    return {
        "protocol": "are.native-command-submission.v1",
        "renderer": "real native ARE CPU C++17",
        "native_binary_sha256": bridge.binary_sha256,
        "packet_sha256": packet.command_sha256,
        "submitted_draws": len(packet.commands),
        **counts,
        "rgba_sha256": hashlib.sha256(framebuffer.color_buffer.tobytes()).hexdigest(),
        "depth_sha256": hashlib.sha256(framebuffer.depth_buffer.tobytes()).hexdigest(),
        "vulkan_command_buffer": False,
        "vulkan_icd": False,
        "spirv_native_cpp_execution": False,
        "unity_runtime": False,
    }
