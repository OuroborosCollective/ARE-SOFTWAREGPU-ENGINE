"""Shared fail-closed admission policy for experimental HTTP and binary TCP.

Bounds are checked BEFORE decoding tensor buffers or starting any CPU worker.
They are not a substitute for TLS, host isolation or kernel resource controls.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hmac
import math
import os
import re
import struct


ALLOWED_METHODS = frozenset({
    "device_info", "gemm", "activation", "vector_add",
    "render_mesh", "physics_step", "boids_swarm",
})
_TENSOR_DTYPES = {"float32": 4, "<f4": 4, ">f4": 4,
                  "float64": 8, "<f8": 8, ">f8": 8}
_BIND_HOST = "127.0.0.1"


class RequestRejected(ValueError):
    """Deliberately generic error code: never contains a client payload."""

    def __init__(self, code: str, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class SecurityLimits:
    max_request_bytes: int = 262_144
    max_response_bytes: int = 1_048_576
    max_elements: int = 16_384
    max_render_pixels: int = 65_536
    max_vertices: int = 3_000
    max_triangles: int = 3_000
    max_compute_ops: int = 10_000_000
    max_clients: int = 4
    max_jobs: int = 2
    io_timeout_seconds: float = 2.0
    worker_timeout_seconds: float = 12.0
    worker_virtual_memory_bytes: int = 4 * 1024**3

    def __post_init__(self):
        caps = {
            "max_request_bytes": (256, 262_144),
            "max_response_bytes": (1024, 1_048_576),
            "max_elements": (1, 16_384),
            "max_render_pixels": (1, 65_536),
            "max_vertices": (1, 3_000),
            "max_triangles": (1, 3_000),
            "max_compute_ops": (1, 10_000_000),
            "max_clients": (1, 16),
            "max_jobs": (1, 4),
            "worker_virtual_memory_bytes": (256 * 1024**2, 4 * 1024**3),
        }
        for field, (low, high) in caps.items():
            value = getattr(self, field)
            if type(value) is not int or not low <= value <= high:
                raise ValueError("INVALID_SECURITY_LIMIT_" + field.upper())
        for field, low, high in (
            ("io_timeout_seconds", .1, 10.0),
            ("worker_timeout_seconds", .01, 30.0),
        ):
            value = getattr(self, field)
            if type(value) not in (float, int) or not low <= value <= high:
                raise ValueError("INVALID_SECURITY_LIMIT_" + field.upper())


def ensure_loopback(host: str) -> None:
    # No other address, hostname alias, proxy bind or dual-stack listener.
    # Remote use needs a separate audited mutually authenticated TLS gateway.
    if host != _BIND_HOST:
        raise ValueError("REMOTE_BIND_FORBIDDEN_UNTIL_TLS_GATE")


def get_token(token: str | None) -> str:
    if token is None:
        token = os.environ.get("SOFTWAREGPU_AUTH_TOKEN", "")
    if (not isinstance(token, str) or not 32 <= len(token) <= 256 or
            len(set(token)) < 12 or not token.isascii() or
            any(ord(c) < 33 or ord(c) > 126 for c in token)):
        raise ValueError("AUTH_TOKEN_REQUIRED_32_TO_256_RANDOM_PRINTABLE_ASCII")
    return token


def authorized(expected: str, presented: str) -> bool:
    return (isinstance(presented, str) and
            hmac.compare_digest(expected.encode("ascii"),
                                presented.encode("utf-8", "replace")))


def bounded_json(document, depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if depth > 14 or counter[0] > 30_000:
        raise RequestRejected("JSON_STRUCTURE_LIMIT")
    if isinstance(document, (tuple, list)):
        for value in document:
            bounded_json(value, depth + 1, counter)
    elif isinstance(document, dict):
        for key, value in document.items():
            if not isinstance(key, str) or len(key) > 128:
                raise RequestRejected("JSON_KEY_LIMIT")
            bounded_json(value, depth + 1, counter)
    elif isinstance(document, float) and not math.isfinite(document):
        raise RequestRejected("NONFINITE_NUMBER")
    elif isinstance(document, int) and document.bit_length() > 64:
        raise RequestRejected("INTEGER_LIMIT")
    elif not isinstance(document, (str, int, float, bool, type(None))):
        raise RequestRejected("JSON_TYPE_INVALID")


def _positive_int(value, limit: int) -> int:
    if type(value) is not int or not 1 <= value <= limit:
        raise RequestRejected("DIMENSION_LIMIT")
    return value


def _finite_number(value, low: float, high: float) -> float:
    if type(value) not in (int, float):
        raise RequestRejected("NUMERIC_PARAMETER_INVALID")
    converted = float(value)
    if not math.isfinite(converted) or not low <= converted <= high:
        raise RequestRejected("NUMERIC_PARAMETER_OUT_OF_RANGE")
    return converted


def tensor_shape(value, limits: SecurityLimits) -> tuple[int, ...]:
    """Validate metadata and payload size without allocating a NumPy array."""
    if isinstance(value, dict):
        if value.get("__tensor__") is not True:
            raise RequestRejected("TENSOR_ENCODING_INVALID")
        shape = value.get("shape")
        if not isinstance(shape, list) or not 1 <= len(shape) <= 3:
            raise RequestRejected("TENSOR_RANK_INVALID")
        dimensions = tuple(_positive_int(n, limits.max_elements) for n in shape)
        elements = math.prod(dimensions)
        if elements > limits.max_elements:
            raise RequestRejected("TENSOR_ELEMENTS_LIMIT", 413)
        item_size = _TENSOR_DTYPES.get(value.get("dtype"))
        if item_size is None:
            raise RequestRejected("TENSOR_DTYPE_UNSUPPORTED")
        payload = value.get("data_b64")
        if not isinstance(payload, str) or len(payload) > limits.max_request_bytes:
            raise RequestRejected("TENSOR_PAYLOAD_LIMIT", 413)
        expected = elements * item_size
        if len(payload) != 4 * ((expected + 2) // 3):
            raise RequestRejected("TENSOR_LENGTH_MISMATCH")
        try:
            decoded = base64.b64decode(payload, validate=True)
        except (ValueError, base64.binascii.Error):
            raise RequestRejected("TENSOR_BASE64_INVALID") from None
        if len(decoded) != expected:
            raise RequestRejected("TENSOR_LENGTH_MISMATCH")
        return dimensions

    if not isinstance(value, list) or not value:
        raise RequestRejected("TENSOR_RANK_INVALID")
    total = [0]

    def visit(data, rank):
        if rank > 3:
            raise RequestRejected("TENSOR_RANK_INVALID")
        if not isinstance(data, list):
            _finite_number(data, -1e10, 1e10)
            total[0] += 1
            if total[0] > limits.max_elements:
                raise RequestRejected("TENSOR_ELEMENTS_LIMIT", 413)
            return ()
        if not data:
            raise RequestRejected("EMPTY_TENSOR")
        if len(data) > limits.max_elements:
            raise RequestRejected("TENSOR_ELEMENTS_LIMIT", 413)
        inner = visit(data[0], rank + 1)
        for item in data[1:]:
            if visit(item, rank + 1) != inner:
                raise RequestRejected("TENSOR_RAGGED")
        return (len(data),) + inner

    dimensions = visit(value, 0)
    if len(dimensions) > 3:
        raise RequestRejected("TENSOR_RANK_INVALID")
    return dimensions


def validate_request(method, params, limits: SecurityLimits) -> None:
    if not isinstance(method, str) or method not in ALLOWED_METHODS:
        raise RequestRejected("METHOD_NOT_ALLOWED", 404)
    if not isinstance(params, dict):
        raise RequestRejected("PARAMETERS_MUST_BE_OBJECT")
    bounded_json(params)

    if method == "device_info":
        if params:
            raise RequestRejected("UNEXPECTED_PARAMETERS")
        return
    if method in ("gemm", "vector_add"):
        a = tensor_shape(params.get("a"), limits)
        b = tensor_shape(params.get("b"), limits)
        if method == "vector_add":
            if a != b:
                raise RequestRejected("TENSOR_SHAPE_MISMATCH")
        else:
            if len(a) != 2 or len(b) != 2 or a[1] != b[0]:
                raise RequestRejected("MATRIX_SHAPE_MISMATCH")
            if a[0] * b[1] > limits.max_elements:
                raise RequestRejected("RESULT_ELEMENTS_LIMIT", 413)
            if 2 * a[0] * b[1] * a[1] > limits.max_compute_ops:
                raise RequestRejected("COMPUTE_OPERATIONS_LIMIT", 413)
        return
    if method == "activation":
        tensor_shape(params.get("x"), limits)
        if params.get("type", "relu") not in ("relu", "gelu"):
            raise RequestRejected("ACTIVATION_UNSUPPORTED")
        return
    if method in ("physics_step", "boids_swarm"):
        a = tensor_shape(params.get("positions"), limits)
        b = tensor_shape(params.get("velocities"), limits)
        if len(a) != 2 or a[1] != 3 or a != b:
            raise RequestRejected("ENTITY_SHAPE_MISMATCH")
        _finite_number(params.get("dt", .016), .000001, 1.0)
        if method == "boids_swarm":
            _finite_number(params.get("max_speed", 10.0), .000001, 1000)
        else:
            bounds = params.get("world_bounds", [-500, 500, -500, 500, 0, 200])
            if not isinstance(bounds, list) or len(bounds) != 6:
                raise RequestRejected("WORLD_BOUNDS_INVALID")
            for idx in range(0, 6, 2):
                if _finite_number(bounds[idx], -1e7, 1e7) >= _finite_number(bounds[idx + 1], -1e7, 1e7):
                    raise RequestRejected("WORLD_BOUNDS_INVALID")
        return
    if method == "render_mesh":
        width = _positive_int(params.get("width", 256), 256)
        height = _positive_int(params.get("height", 256), 256)
        if width * height > limits.max_render_pixels:
            raise RequestRejected("RENDER_PIXELS_LIMIT", 413)
        vertices, faces = params.get("vertices", []), params.get("indices", [])
        if not isinstance(vertices, list) or len(vertices) > limits.max_vertices:
            raise RequestRejected("VERTICES_LIMIT", 413)
        if not isinstance(faces, list) or len(faces) > limits.max_triangles:
            raise RequestRejected("TRIANGLES_LIMIT", 413)
        if width * height * max(1, len(faces)) > limits.max_compute_ops:
            raise RequestRejected("RENDER_COST_LIMIT", 413)
        for vertex in vertices:
            if not isinstance(vertex, dict) or not isinstance(vertex.get("pos"), list) or len(vertex["pos"]) not in (3, 4):
                raise RequestRejected("VERTEX_INVALID")
            for key, dimensions in (("pos", len(vertex["pos"])), ("norm", 3), ("uv", 2), ("color", 3)):
                if key not in vertex:
                    continue
                val = vertex[key]
                if not isinstance(val, list) or len(val) != dimensions:
                    raise RequestRejected("VERTEX_ATTRIBUTE_INVALID")
                for x in val:
                    _finite_number(x, -1e6, 1e6)
        for face in faces:
            if not isinstance(face, list) or len(face) != 3 or any(
                    type(i) is not int or i < 0 or i >= len(vertices) for i in face):
                raise RequestRejected("TRIANGLE_INDEX_INVALID")
        return
