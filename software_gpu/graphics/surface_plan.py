"""Bounded, deterministic plans for the opt-in CPU tiles-plan backend.

No provider calls or generated code execute here. Colors describe four views
of the same work; only explicit rules affect execution. Corner classification
uses the *same float32 operation order and top-left rule* as dense coverage.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from threading import Lock

import numpy as np

from .geometry import edge_covered

PROTOCOL = "are.surface-plan.v1"
MIN_SCAN_SAMPLES = 64
MIN_BATCH_SAMPLES = 8
MIN_DRAW_SAMPLES_PER_TRIANGLE = 64
MAX_TRACE_TILES = 128
COUNTERS = ("inside", "outside", "boundary", "scan_bypassed",
            "corner_edge_evaluations", "dense_edge_evaluations",
            "skipped_samples", "shaded_samples", "scalar_fragment_calls",
            "batch_fragment_calls")


def classify_tile(s0, s1, s2, left, right, top, bottom):
    """Return outside/inside/boundary; never infer nonlinear shader bounds.

    For finite inputs each separable rounded affine edge is monotone along
    x/y. Its extrema therefore occur at sample-domain corners. Nonfinite
    intermediates fall back to dense coverage. No reassociation or FMA is used.
    """
    px = (np.asarray([left, right], dtype=np.float32) + np.float32(.5))[None, :]
    py = (np.asarray([top, bottom], dtype=np.float32) + np.float32(.5))[:, None]
    all_inside = True
    any_outside = False
    finite = True
    for a, b in ((s1, s2), (s2, s0), (s0, s1)):
        with np.errstate(over="ignore", invalid="ignore"):
            values = (px - a[0]) * (b[1] - a[1]) - (py - a[1]) * (b[0] - a[0])
        if not np.isfinite(values).all():
            finite = False
            continue
        included = edge_covered(values, a, b)
        if not included.any():
            any_outside = True
        all_inside = all_inside and bool(included.all())
    if not finite:
        return "boundary"
    return "outside" if any_outside else ("inside" if all_inside else "boundary")


def equivalent_batch(shader):
    """Resolve an explicitly declared implementation, guarding overrides.

    The declaration binds the scalar function it replaces. A subclass or
    instance overriding that function automatically falls back to scalar.
    Callers remain responsible for the declared batch's semantic equivalence.
    """
    scalar = getattr(shader, "fragment_shader", None)
    declared = getattr(shader, "batch_fragment_equivalent_to", None)
    batch = getattr(shader, "fragment_shader_batch", None)
    if (callable(batch) and declared is not None and
            getattr(scalar, "__func__", scalar) is getattr(declared, "__func__", declared)):
        return batch
    return None


def checked_batch_rgba(batch, varyings, count):
    """Validate an entire tile/triangle result before framebuffer writes."""
    rgba = batch(varyings)
    if (not isinstance(rgba, np.ndarray) or rgba.shape != (count, 4)
            or rgba.dtype.kind not in "iu"
            or np.any(rgba < 0) or np.any(rgba > 255)):
        raise ValueError("BATCH_RGBA_CONTRACT_INVALID")
    return rgba.astype(np.uint8, copy=False)


class PlanTrace:
    """Counters for all work, bounded tile summaries and stable graph digest.

    Counters and selected coordinates are independent of worker completion
    order. No per-pixel nodes, timings or shader payloads enter the graph.
    """
    def __init__(self, coordinates, reference_reason=None, bbox_samples=0, triangle_count=0):
        self.selected = frozenset(sorted(coordinates)[:MAX_TRACE_TILES])
        self.counts = Counter({key: 0 for key in COUNTERS})
        self.tiles = {}
        self.lock = Lock()
        self.tile_count = len(coordinates)
        self.reference_reason = reference_reason
        self.bbox_samples = bbox_samples
        self.triangle_count = triangle_count

    def record(self, coordinate, counts):
        with self.lock:
            self.counts.update(counts)
            if coordinate in self.selected:
                self.tiles[coordinate] = dict(sorted(counts.items()))

    def receipt(self):
        nodes, edges = [], []
        if self.reference_reason:
            for layer, color in (("math", "blue"), ("domain", "purple"),
                                 ("execution", "orange"), ("contract", "green")):
                nodes.append({"id": "draw:" + layer, "layer": layer, "color": color,
                              "route": "tiles-reference", "reason": self.reference_reason})
            edges = [["draw:" + source, "draw:execution"] for source in ("math", "domain", "contract")]
        for (ty, tx), counts in sorted(self.tiles.items()):
            prefix = f"tile:{ty}:{tx}"
            for layer, color in (("math", "blue"), ("domain", "purple"),
                                 ("execution", "orange"), ("contract", "green")):
                node = {"id": prefix + ":" + layer, "layer": layer, "color": color}
                if layer == "domain":
                    node["tile"] = [ty, tx]
                elif layer == "execution":
                    node["observations"] = counts
                elif layer == "math":
                    node["rule"] = "affine-corners-f32-same-order-v1"
                else:
                    node["requirements"] = ["top-left", "strict-depth-less", "submission-order",
                                            "perspective-varyings", "explicit-batch-equivalence"]
                nodes.append(node)
            for source in ("math", "domain", "contract"):
                edges.append([prefix + ":" + source, prefix + ":execution"])
        body = {"protocol": PROTOCOL, "authority": "derived-render-only",
                "provider_calls": 0, "timing_model": "fixed-thresholds-not-runtime-autotuning",
                "scan_min_samples": MIN_SCAN_SAMPLES, "batch_min_samples": MIN_BATCH_SAMPLES,
                "draw_min_bbox_samples_per_triangle": MIN_DRAW_SAMPLES_PER_TRIANGLE,
                "estimated_bbox_samples": self.bbox_samples, "triangle_count": self.triangle_count,
                "decision": "tiles-reference" if self.reference_reason else "planned",
                "reason": self.reference_reason,
                "tile_count": self.tile_count, "trace_tile_limit": MAX_TRACE_TILES,
                "trace_truncated": not self.reference_reason and self.tile_count > MAX_TRACE_TILES,
                "counts": None if self.reference_reason else dict(sorted(self.counts.items())),
                "nodes": nodes, "edges": edges}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return dict(body, plan_sha256=hashlib.sha256(raw).hexdigest())
