"""Opt-in, bounded per-pixel evidence from *actual* CPU tile shader calls.

This module does not affect normal draw_mesh and has no authority over game
state, training, device selection, or renderer policy. Source revision is
caller-declared; implementation file hashes are computed independently.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import re

import numpy as np


PROTOCOL = "are.cpu-pixel-forensics.v1"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
MAX_EVENTS = 256


def _f32_bits(value):
    """Exact little-endian float32 bits, without decimal/string rounding."""
    return np.asarray([value], dtype="<f4").tobytes().hex()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _hash_scene(vertices, faces, shader):
    h = hashlib.sha256(b"are.pixel-trace.scene.v1\0")
    h.update((type(shader).__module__ + "." + type(shader).__qualname__).encode())
    for vertex in vertices:
        for name in ("position", "color", "uv", "normal"):
            value = getattr(vertex, name, None)
            h.update(name.encode("ascii") + b"\0")
            if value is None:
                h.update(b"none\0")
                continue
            arr = np.asarray(value)
            # Object arrays encode process-dependent pointer bytes, not canonical geometry.
            if arr.dtype.hasobject:
                raise ValueError("PIXEL_TRACE_UNHASHABLE_INPUT")
            h.update(str(arr.dtype).encode("ascii") + b"\0")
            h.update(str(arr.shape).encode("ascii") + b"\0")
            h.update(arr.tobytes(order="C"))
    h.update(json.dumps([[int(i) for i in face] for face in faces],
                        separators=(",", ":"), allow_nan=False).encode("ascii"))
    return h.hexdigest()


class PixelForensicTrace:
    """One bounded pixel across an explicit ordered series of real tile draws."""

    def __init__(self, framebuffer, x, y, source_revision, max_events=64):
        if (type(x) is not int or type(y) is not int
                or not (0 <= x < framebuffer.width and 0 <= y < framebuffer.height)):
            raise ValueError("PIXEL_TRACE_PIXEL_INVALID")
        if type(max_events) is not int or not 1 <= max_events <= MAX_EVENTS:
            raise ValueError("PIXEL_TRACE_BUDGET_INVALID")
        if not isinstance(source_revision, str) or not SHA40.fullmatch(source_revision):
            raise ValueError("PIXEL_TRACE_REVISION_INVALID")
        if framebuffer.color_buffer.dtype != np.dtype("uint8") or framebuffer.depth_buffer.dtype != np.dtype("float32"):
            raise ValueError("PIXEL_TRACE_FRAMEBUFFER_FORMAT")
        self.fb = framebuffer
        self.x, self.y = x, y
        self.source_revision = source_revision
        self.max_events = max_events
        self.events = []
        self.draws = []
        self.discarded_primitives = []
        self._discarded_count = 0
        self._active = None
        self._invalid = False
        self._sealed = False
        self._final_owner = None
        self._initial_rgba_hash = hashlib.sha256(framebuffer.color_buffer.tobytes()).hexdigest()
        self._initial_depth_hash = hashlib.sha256(framebuffer.depth_buffer.tobytes()).hexdigest()

    def start_draw(self, vertices, faces, shader, triangles, source_ids):
        if self._invalid or self._sealed:
            raise ValueError("PIXEL_TRACE_CLOSED")
        if self._active is not None:
            raise ValueError("PIXEL_TRACE_DRAW_ALREADY_ACTIVE")
        if len(triangles) != len(source_ids):
            raise ValueError("PIXEL_TRACE_SOURCE_MAP_MISMATCH")
        seen = set(source_ids)
        discarded = [i for i in range(len(faces)) if i not in seen]
        if (len(self.events) + self._discarded_count + len(triangles) + len(discarded) > self.max_events):
            raise ValueError("PIXEL_TRACE_QUOTA_EXCEEDED")
        draw_id = len(self.draws)
        if draw_id >= 32:
            raise ValueError("PIXEL_TRACE_DRAW_LIMIT")
        self.draws.append({
            "draw_id": draw_id,
            "input_primitive_count": len(faces),
            "raster_triangle_count": len(triangles),
            "scene_sha256": _hash_scene(vertices, faces, shader),
        })
        self.discarded_primitives.append(discarded)
        self._discarded_count += len(discarded)
        indexed = {}
        per_source_piece = {}
        for j, (tri, primitive_id) in enumerate(zip(triangles, source_ids)):
            piece = per_source_piece.get(primitive_id, 0)
            per_source_piece[primitive_id] = piece + 1
            event = {
                "draw_id": draw_id,
                "primitive_id": int(primitive_id),
                "raster_triangle_id": j,
                "clip_piece": piece,
                "decision": "pixel_outside_candidate",
                "shader_called": False,
            }
            indexed[id(tri)] = event
            self.events.append(event)
        self._active = indexed

    def record_edge(self, triangle, weights, covered, previous_depth, candidate_depth=None):
        event = self._active[id(triangle)]
        event["edge_f32_bits"] = [_f32_bits(w) for w in weights]
        event["edge_pass"] = bool(covered)
        event["depth_before_f32_bits"] = _f32_bits(previous_depth)
        if not covered:
            event["decision"] = "edge_reject"
            return
        event["depth_candidate_f32_bits"] = _f32_bits(candidate_depth)
        event["depth_rule"] = "strict_less"
        event["decision"] = ("shader_pending" if candidate_depth < previous_depth else "depth_reject")

    def record_fragment(self, triangle, rgba, depth):
        event = self._active[id(triangle)]
        if event["decision"] != "shader_pending":
            raise ValueError("PIXEL_TRACE_UNEXPECTED_SHADER_CALL")
        event["shader_called"] = True
        event["decision"] = "shader_call"
        event["rgba"] = [int(x) for x in rgba]
        event["written_depth_f32_bits"] = _f32_bits(depth)
        self._final_owner = {k: event[k] for k in ("draw_id", "primitive_id", "raster_triangle_id")}

    def end_draw(self):
        if self._active is None:
            raise ValueError("PIXEL_TRACE_NO_ACTIVE_DRAW")
        if any(x["decision"] == "shader_pending" for x in self._active.values()):
            raise ValueError("PIXEL_TRACE_MISSING_SHADER_CALL")
        self._active = None

    def invalidate(self):
        """Never publish a complete receipt after a failed real raster call."""
        self._invalid = True
        self._active = None

    def finish(self):
        if self._invalid:
            raise ValueError("PIXEL_TRACE_INCOMPLETE")
        if self._sealed:
            raise ValueError("PIXEL_TRACE_ALREADY_FINISHED")
        if self._active is not None:
            raise ValueError("PIXEL_TRACE_DRAW_ACTIVE")
        self._sealed = True
        root = Path(__file__).resolve().parent
        sources = {p: hashlib.sha256((root / p).read_bytes()).hexdigest()
                   for p in ("pixel_trace.py", "rasterizer.py", "tile_backend.py", "geometry.py")}
        value = {
            "protocol": PROTOCOL,
            "declared_repository_revision": self.source_revision,
            "revision_verified": False,
            "renderer_source_sha256": sources,
            "pixel": {"x": self.x, "y": self.y},
            "max_events": self.max_events,
            "complete": True,
            "initial_frame_rgba_sha256": self._initial_rgba_hash,
            "initial_frame_depth_sha256": self._initial_depth_hash,
            "draws": self.draws,
            "draw_sequence_sha256": _digest(self.draws),
            "discarded_primitives": self.discarded_primitives,
            "events": self.events,
            "final_owner": self._final_owner,
            "final_rgba": [int(c) for c in self.fb.color_buffer[self.y, self.x]],
            "final_depth_f32_bits": _f32_bits(self.fb.depth_buffer[self.y, self.x]),
            "full_frame_rgba_sha256": hashlib.sha256(self.fb.color_buffer.tobytes()).hexdigest(),
            "full_frame_depth_sha256": hashlib.sha256(self.fb.depth_buffer.tobytes()).hexdigest(),
            "authority": "offline_cpu_diagnostic_only",
        }
        value["receipt_sha256"] = _digest(value)
        return value


def inspect_trace_receipt(receipt):
    """Verify a bounded immutable JSON receipt and show a read-only analysis."""
    if not isinstance(receipt, dict) or receipt.get("protocol") != PROTOCOL:
        raise ValueError("PIXEL_TRACE_PROTOCOL")
    if (type(receipt.get("max_events")) is not int
            or not 1 <= receipt["max_events"] <= MAX_EVENTS
            or not isinstance(receipt.get("events"), list)
            or not isinstance(receipt.get("draws"), list)
            or len(receipt["draws"]) > 32
            or not isinstance(receipt.get("discarded_primitives"), list)
            or len(receipt["discarded_primitives"]) != len(receipt["draws"])
            or any(not isinstance(group, list) for group in receipt["discarded_primitives"])
            or (len(receipt["events"]) + sum(len(group) for group in receipt["discarded_primitives"])
                > receipt["max_events"])):
        raise ValueError("PIXEL_TRACE_BUDGET_INVALID")
    digest = receipt.get("receipt_sha256")
    if not isinstance(digest, str) or not hmac.compare_digest(
            digest, _digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})):
        raise ValueError("PIXEL_TRACE_DIGEST_MISMATCH")
    lines = [
        "# CPU Pixel Forensics (offline analysis; no game authority)",
        f'Pixel: ({receipt["pixel"]["x"]}, {receipt["pixel"]["y"]})',
        f'Declared source revision (not externally verified): {receipt["declared_repository_revision"]}',
        f'RGBA SHA256: {receipt["full_frame_rgba_sha256"]}',
        f'Depth SHA256: {receipt["full_frame_depth_sha256"]}',
        f'Receipt SHA256: {digest}',
        f'Final RGBA: {receipt["final_rgba"]}; Depth float32 bits: {receipt["final_depth_f32_bits"]}',
        f'Final depth owner: {receipt["final_owner"]}',
        "| Draw | Source primitive | Clipped triangle | Edge/depth/shader decision |",
        "|:--|--:|--:|:--|",
    ]
    for event in receipt["events"]:
        lines.append(f'| {event["draw_id"]} | {event["primitive_id"]} | '
                     f'{event["raster_triangle_id"]} | {event["decision"]} |')
    return "\n".join(lines) + "\n"
