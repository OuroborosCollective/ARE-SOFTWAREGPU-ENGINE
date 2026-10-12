"""Bounded, renderer-local cache of pure vertex setup and tile candidates.

Full input hashing detects in-place edits without trusting caller revisions.
Only the two known pure vertex entry points are admitted. Fragment shaders,
coverage and depth always execute again. Inputs must not mutate during a draw,
as on the uncached renderer. Concurrent draws into one renderer are unsupported.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import sys
import time
from types import MappingProxyType

import numpy as np

from .batch_shader import VertexColorShader
from .geometry import prepare_triangles
from .shader import BlinnPhongShader, Vertex
from .tile_backend import bin_triangles


PROTOCOL = "are.preparation-cache.v1"


def _array_hash(digest, value):
    if type(value) is not np.ndarray or value.dtype.kind not in "biufc":
        return False
    # Include layout too: equal values need not have equal evaluation layout.
    digest.update(repr((value.dtype.str, value.shape, value.strides)).encode())
    digest.update(value.tobytes(order="C"))
    return True


def input_key(vertices, indices, shader, width, height, tile_size, scan_min_samples):
    """Return a content key or explicit bypass; never consume an input iterator."""
    function = getattr(getattr(shader, "vertex_shader", None), "__func__", None)
    if function is VertexColorShader.vertex_preparation_equivalent_to:
        fields, state, contract = ("position", "color"), (), "vertex-color-v1"
    elif function is BlinnPhongShader.vertex_preparation_equivalent_to:
        fields = ("position", "normal", "uv", "color")
        state, contract = (shader.mvp, shader.normal_matrix), "blinn-phong-vertex-v1"
    else:
        return None, "undeclared-vertex-shader"
    if (type(vertices) not in (list, tuple) or type(indices) not in (list, tuple, np.ndarray)
            or any(type(vertex) is not Vertex for vertex in vertices)):
        return None, "unsupported-input-container"
    digest = hashlib.sha256()
    digest.update(repr((PROTOCOL, contract, width, height, tile_size,
                        scan_min_samples, len(vertices), fields)).encode())
    for value in state:
        if not _array_hash(digest, value):
            return None, "unsupported-shader-state"
    for vertex in vertices:
        for field in fields:
            if not _array_hash(digest, getattr(vertex, field)):
                return None, "unsupported-vertex-array"
    try:
        faces = np.asarray(indices)
    except (ValueError, TypeError):
        return None, "unsupported-indices"
    if len(indices) and (faces.dtype.kind not in "iu" or faces.ndim != 2 or faces.shape[1] != 3):
        return None, "unsupported-indices"
    _array_hash(digest, faces)
    return digest.hexdigest(), None


def _freeze_triangles(triangles):
    """Detach every retained array from the caller; immutable bytes own storage."""
    arrays, attrs = {}, {}

    def freeze_array(value):
        if id(value) not in arrays:
            arrays[id(value)] = np.frombuffer(value.tobytes(order="C"),
                                              dtype=value.dtype).reshape(value.shape)
        return arrays[id(value)]

    def freeze_attrs(value):
        if id(value) not in attrs:
            attrs[id(value)] = MappingProxyType({
                key: freeze_array(item) if isinstance(item, np.ndarray) else item
                for key, item in value.items()})
        return attrs[id(value)]

    return tuple(tuple(freeze_array(value) if index < 3 else
                       freeze_attrs(value) if 6 <= index < 9 else value
                       for index, value in enumerate(triangle)) for triangle in triangles)


def retained_bytes(value, seen=None):
    """Account retained Python containers and array owners once, including aliases.

    This is a retention budget, not an RSS or transient-allocation limit.
    MappingProxyType additionally charges its backing dict's shallow size.
    """
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    total = sys.getsizeof(value)
    if isinstance(value, np.ndarray):
        if value.base is not None:
            total += retained_bytes(value.base, seen)
    elif isinstance(value, MappingProxyType):
        total += sys.getsizeof(dict(value))
        total += sum(retained_bytes(key, seen) + retained_bytes(item, seen)
                     for key, item in value.items())
    elif isinstance(value, (tuple, list)):
        total += sum(retained_bytes(item, seen) for item in value)
    elif hasattr(value, "__dataclass_fields__"):
        total += retained_bytes(vars(value), seen)
    elif isinstance(value, dict):
        total += sum(retained_bytes(key, seen) + retained_bytes(item, seen)
                     for key, item in value.items())
    return total


@dataclass(frozen=True)
class PreparedDraw:
    triangles: tuple
    bins: object


class PreparationCache:
    """LRU with explicit byte/entry bounds. Cache contents have no world authority."""
    def __init__(self, max_bytes, max_entries=8):
        if type(max_bytes) is not int or max_bytes < 1 or type(max_entries) is not int or max_entries < 1:
            raise ValueError("PREPARATION_CACHE_BUDGET_INVALID")
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self._entries = OrderedDict()
        self.bytes = 0

    def clear(self):
        self._entries.clear()
        self.bytes = 0

    def prepare(self, vertices, indices, shader, width, height, tile_size, scan_min_samples=None):
        start = time.perf_counter_ns()
        key, reason = input_key(vertices, indices, shader, width, height, tile_size, scan_min_samples)
        key_ms = (time.perf_counter_ns() - start) / 1e6
        hit = key is not None and key in self._entries
        evicted = 0
        setup_start = time.perf_counter_ns()
        if hit:
            prepared, _ = self._entries[key]
            self._entries.move_to_end(key)
            status = "hit"
        else:
            triangles = prepare_triangles(vertices, indices, shader, width, height)
            # Unknown vertex functions remain the original path, including effects.
            if key is not None:
                triangles = _freeze_triangles(triangles)
            prepared = PreparedDraw(triangles, bin_triangles(
                triangles, width, height, tile_size, scan_min_samples))
            status = "bypass" if key is None else "miss"
            if key is not None:
                charge = retained_bytes((key, prepared)) + 128  # LRU record/node allowance
                if charge > self.max_bytes:
                    status, reason = "bypass", "entry-exceeds-budget"
                else:
                    while self._entries and (self.bytes + charge > self.max_bytes
                                             or len(self._entries) >= self.max_entries):
                        _, (_, old_charge) = self._entries.popitem(last=False)
                        self.bytes -= old_charge
                        evicted += 1
                    self._entries[key] = (prepared, charge)
                    self.bytes += charge
        receipt = {"protocol": PROTOCOL, "authority": "derived-render-only", "status": status,
                   "reason": reason, "key_sha256": key, "entries": len(self._entries),
                   "retained_bytes": self.bytes, "max_bytes": self.max_bytes,
                   "max_entries": self.max_entries, "evicted": evicted,
                   "triangles": len(prepared.triangles), "tiles": len(prepared.bins.tasks),
                   "key_ms": key_ms, "setup_ms": (time.perf_counter_ns() - setup_start) / 1e6}
        return prepared, receipt
