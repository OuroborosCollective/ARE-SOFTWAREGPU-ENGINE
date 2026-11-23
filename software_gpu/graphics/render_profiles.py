"""Explicit opt-in CPU material passes for Issue #285.

The opaque SoftwareRasterizer.draw_mesh path and native/PBR workers are untouched.
All draws reuse the shared ARE geometry preparation and tile coverage/depth path.
Transparency is a material operation, not a synonym for disabling depth writes.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import subprocess

import numpy as np

from .framebuffer import Framebuffer
from .geometry import prepare_triangles
from .tile_backend import rasterize_tiles


def _rgba8(value):
    try:
        channels = tuple(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("OPTIN_RGBA8_INVALID") from exc
    if len(channels) != 4 or any(
        isinstance(c, (bool, np.bool_)) or
        not isinstance(c, (int, np.integer)) or not 0 <= int(c) <= 255
        for c in channels
    ):
        raise ValueError("OPTIN_RGBA8_INVALID")
    return tuple(int(c) for c in channels)


def _decode(byte):
    u = byte / 255.0
    return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4


def _encode(linear):
    v = max(0.0, min(1.0, linear))
    srgb = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1.0 / 2.4) - 0.055
    return max(0, min(255, int(math.floor(srgb * 255.0 + 0.5))))


@dataclass(frozen=True)
class FragmentPolicy:
    """Explicit fragment operation used only by NumPy tile opt-in draws.

    Opaque and alpha-test write both color and strictly-nearer depth.
    Alpha blend tests against existing opaque depth without writing depth,
    but writes composited color. Shadow-depth writes depth alone.
    """
    mode: str
    cutoff: int = 128

    def __post_init__(self):
        if self.mode not in ("opaque", "alpha-test", "alpha-blend", "shadow-depth"):
            raise ValueError("OPTIN_MATERIAL_MODE_UNSUPPORTED")
        if type(self.cutoff) is not int or not 0 <= self.cutoff <= 255:
            raise ValueError("OPTIN_ALPHA_CUTOFF_INVALID")
        if self.mode != "alpha-test" and self.cutoff != 128:
            raise ValueError("OPTIN_ALPHA_CUTOFF_REQUIRES_TEST")

    def apply(self, fb, y, x, depth, rgba):
        rgba = _rgba8(rgba)
        if self.mode == "shadow-depth":
            fb.depth_buffer[y, x] = depth
            return
        if self.mode == "alpha-test":
            if rgba[3] < self.cutoff:
                return  # Discard does not claim the depth owner.
        if self.mode in ("opaque", "alpha-test"):
            fb.depth_buffer[y, x] = depth
            fb.color_buffer[y, x] = rgba
            return
        # Straight-alpha source-over in *linear* RGB, not byte-wise sRGB.
        # Blend is behind early-Z against the existing opaque depth. Transparent
        # samples keep that depth untouched while contributing all overdraw.
        sa = rgba[3] / 255.0
        if sa == 0.0:
            return
        if sa == 1.0:
            fb.color_buffer[y, x] = rgba
            return
        old = tuple(int(c) for c in fb.color_buffer[y, x])
        da = old[3] / 255.0
        out_a = sa + da * (1.0 - sa)
        rgb = []
        for k in range(3):
            linear = (_decode(rgba[k]) * sa +
                      _decode(old[k]) * da * (1.0 - sa))
            rgb.append(_encode(linear / out_a) if out_a else 0)
        fb.color_buffer[y, x] = (*rgb, int(math.floor(out_a * 255.0 + 0.5)))


def _matrix(matrix):
    array = np.asarray(matrix, dtype=np.float64)
    if array.shape != (4, 4) or not np.isfinite(array).all():
        raise ValueError("OPTIN_LIGHT_MATRIX_INVALID")
    return array.copy()


@dataclass(frozen=True)
class ShadowMap:
    """Frozen Float32 light-space depth; outside the light frustum is lit."""
    depth: np.ndarray
    light_mvp: np.ndarray

    def __post_init__(self):
        depth = np.asarray(self.depth)
        matrix = _matrix(self.light_mvp)
        if depth.ndim != 2 or not depth.size or depth.dtype != np.float32:
            raise ValueError("OPTIN_SHADOW_DEPTH_INVALID")
        if not np.isfinite(depth).all():
            raise ValueError("OPTIN_SHADOW_DEPTH_INVALID")
        frozen = depth.copy()
        frozen.setflags(write=False)
        matrix.setflags(write=False)
        object.__setattr__(self, "depth", frozen)
        object.__setattr__(self, "light_mvp", matrix)

    def visible(self, world, bias=0.0001):
        if not isinstance(bias, (float, int)) or isinstance(bias, bool) or (
                not math.isfinite(bias) or bias < 0.0 or bias > 0.1):
            raise ValueError("OPTIN_SHADOW_BIAS_INVALID")
        point = np.asarray(world, dtype=np.float64)
        if point.shape != (3,) or not np.isfinite(point).all():
            raise ValueError("OPTIN_SHADOW_WORLD_INVALID")
        clip = self.light_mvp @ np.append(point, 1.0)
        if not np.isfinite(clip).all() or clip[3] <= 1.0e-7:
            raise ValueError("OPTIN_SHADOW_PROJECTION_INVALID")
        ndc = clip[:3] / clip[3]
        if np.any(ndc < -1.0) or np.any(ndc > 1.0):
            return True
        h, w = self.depth.shape
        ix = min(w - 1, int((ndc[0] + 1.0) * 0.5 * w))
        iy = min(h - 1, int((1.0 - ndc[1]) * 0.5 * h))
        # Inclusive compare is deliberate for self-shadow equality; geometric
        # ownership in the light map remains the ordinary strict-less first-wins.
        return bool(ndc[2] <= float(self.depth[iy, ix]) + float(bias))


class _LightDepthShader:
    def __init__(self, light_mvp):
        self.light_mvp = light_mvp

    def vertex_shader(self, vertex):
        return self.light_mvp @ np.asarray(vertex.position, dtype=np.float64), {}

    def fragment_shader(self, varyings):
        return (0, 0, 0, 255)


class ShadowedShader:
    """Explicitly shades base RGB with a frozen CPU shadow map.

    Input Vertex.position is the world-space point. The base shader may project
    it for the camera; no hidden world reconstruction or native PBR claim.
    """
    def __init__(self, base_shader, shadow_map: ShadowMap, ambient=0.25, bias=0.0001):
        if type(shadow_map) is not ShadowMap:
            raise ValueError("OPTIN_SHADOW_MAP_REQUIRED")
        if (not isinstance(ambient, (int, float)) or isinstance(ambient, bool)
                or not math.isfinite(ambient) or not 0 <= ambient <= 1):
            raise ValueError("OPTIN_SHADOW_AMBIENT_INVALID")
        if (not isinstance(bias, (float, int)) or isinstance(bias, bool)
                or not math.isfinite(bias) or not 0 <= bias <= 0.1):
            raise ValueError("OPTIN_SHADOW_BIAS_INVALID")
        self.base = base_shader
        self.shadow = shadow_map
        self.ambient = float(ambient)
        self.bias = float(bias)

    def vertex_shader(self, vertex):
        clip, varying = self.base.vertex_shader(vertex)
        if not isinstance(varying, dict) or "are_world_position" in varying:
            raise ValueError("OPTIN_SHADOW_VARYING_CONFLICT")
        out = dict(varying)
        out["are_world_position"] = np.asarray(vertex.position[:3], dtype=np.float64)
        return clip, out

    def fragment_shader(self, varying):
        rgba = _rgba8(self.base.fragment_shader(varying))
        if self.shadow.visible(varying["are_world_position"], self.bias):
            return rgba
        return tuple(_encode(_decode(c) * self.ambient) for c in rgba[:3]) + (rgba[3],)


def _git_head():
    try:
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                capture_output=True, text=True, check=True, timeout=5)
        sha = result.stdout.strip()
        return sha if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha) else None
    except (OSError, subprocess.SubprocessError):
        return None


def frame_receipt(frame, profile, scene):
    """Full RGBA8/Float32 fingerprints, measured from actual frame buffers."""
    if not isinstance(scene, str) or not scene or len(scene) > 128:
        raise ValueError("OPTIN_SCENE_LABEL_INVALID")
    root = Path(__file__).resolve().parents[2]
    src = ("software_gpu/graphics/render_profiles.py",
           "software_gpu/graphics/tile_backend.py",
           "software_gpu/graphics/geometry.py")
    receipt = {
        "protocol": "are.cpu-material-frame.v1",
        "profile": profile,
        "scene_label": scene,
        "size": [int(frame.width), int(frame.height)],
        "rgba_sha256": hashlib.sha256(frame.color_buffer.tobytes()).hexdigest(),
        "depth_sha256": hashlib.sha256(frame.depth_buffer.tobytes()).hexdigest(),
        "depth_dtype": str(frame.depth_buffer.dtype),
        "source_sha256": {f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in src},
        "head_sha": _git_head(),
        "no_gpu_or_fps_claim": True,
    }
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False)
    receipt["sha256"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return receipt


class OptInCpuRenderer:
    """Restricted CPU tiles only. All drawing is transactional per public call."""
    def __init__(self, framebuffer: Framebuffer, tile_size=16, workers=1):
        if type(framebuffer) is not Framebuffer or framebuffer.width < 1 or framebuffer.height < 1:
            raise ValueError("OPTIN_FRAMEBUFFER_INVALID")
        if (type(tile_size) is not int or not 1 <= tile_size <= 256 or
                type(workers) is not int or not 1 <= workers <= 32):
            raise ValueError("OPTIN_WORKER_CONFIG_INVALID")
        self.fb = framebuffer
        self.tile_size = tile_size
        self.workers = workers
        self.executor = ThreadPoolExecutor(max_workers=workers,
                                           thread_name_prefix="ARE_OptInTile")
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        if not self._closed:
            self.executor.shutdown(wait=True)
            self._closed = True

    def _draw(self, frame, vertices, indices, shader, policy):
        if self._closed:
            raise ValueError("OPTIN_RENDERER_CLOSED")
        triangles = prepare_triangles(vertices, indices, shader, frame.width, frame.height)
        rasterize_tiles(frame, triangles, shader, self.tile_size,
                        self.executor, self.workers, fragment_policy=policy)

    def _atomic(self, operations):
        staged = Framebuffer(self.fb.width, self.fb.height)
        staged.color_buffer[:] = self.fb.color_buffer
        staged.depth_buffer[:] = self.fb.depth_buffer
        for vertices, indices, shader, policy in operations:
            self._draw(staged, vertices, indices, shader, policy)
        self.fb.color_buffer[:] = staged.color_buffer
        self.fb.depth_buffer[:] = staged.depth_buffer

    def draw_opaque(self, vertices, indices, shader):
        self._atomic([(vertices, indices, shader, FragmentPolicy("opaque"))])

    def draw_alpha_test(self, vertices, indices, shader, cutoff=128):
        self._atomic([(vertices, indices, shader, FragmentPolicy("alpha-test", cutoff))])

    def blend_sorted(self, draws):
        """Draw-level sort: descending NDC Z (far first), stable submission ties.

        Each draw is (sort_ndc_z, vertices, indices, shader). Geometry within
        a draw retains its submitted order. Split intersecting transparent
        meshes into appropriate draw units; no order-independent transparency.
        """
        if not isinstance(draws, (list, tuple)):
            raise ValueError("OPTIN_BLEND_DRAWS_INVALID")
        operations = []
        for row in draws:
            if not isinstance(row, (list, tuple)) or len(row) != 4:
                raise ValueError("OPTIN_BLEND_DRAWS_INVALID")
            z, vertices, indices, shader = row
            if (not isinstance(z, (float, int, np.floating)) or isinstance(z, bool)
                    or not math.isfinite(z) or not -1.0 <= z <= 1.0):
                raise ValueError("OPTIN_BLEND_SORT_DEPTH_INVALID")
            operations.append((float(z), vertices, indices, shader,
                               FragmentPolicy("alpha-blend")))
        sorted_operations = sorted(operations, key=lambda row: -row[0])
        self._atomic([row[1:] for row in sorted_operations])

    def make_shadow_map(self, draws, light_mvp, resolution=64):
        """World-space casters -> real depth-only light-space tile raster."""
        matrix = _matrix(light_mvp)
        if type(resolution) is not int or not 1 <= resolution <= 2048:
            raise ValueError("OPTIN_SHADOW_RESOLUTION_INVALID")
        if not isinstance(draws, (list, tuple)):
            raise ValueError("OPTIN_SHADOW_DRAWS_INVALID")
        stage = Framebuffer(resolution, resolution)
        stage.clear(0, 0, 0, 255, depth=1.0)
        shader = _LightDepthShader(matrix)
        for row in draws:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                raise ValueError("OPTIN_SHADOW_DRAWS_INVALID")
            vertices, indices = row
            self._draw(stage, vertices, indices, shader, FragmentPolicy("shadow-depth"))
        return ShadowMap(stage.depth_buffer, matrix)


def resolve_4x(frame):
    """4 sample centers per logical pixel at (0.25/0.75, 0.25/0.75).

    Explicit per-sample shading is rendered at 2x width/height. Resolve:
    alpha-weighted linear RGB, averaged alpha, minimum Float32 depth. This is
    not a substitution for the legacy native/PBR MSAA or its sample layout.
    """
    if (type(frame) is not Framebuffer or frame.width < 2 or frame.height < 2 or
            frame.width % 2 or frame.height % 2):
        raise ValueError("OPTIN_4X_RESOLVE_DIMENSIONS_INVALID")
    h, w = frame.height // 2, frame.width // 2
    rgba = frame.color_buffer.astype(np.float64)
    a = rgba[..., 3] / 255.0
    rgb = rgba[..., :3] / 255.0
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    premult = (linear * a[..., None]).reshape(h, 2, w, 2, 3).mean(axis=(1, 3))
    out_a = a.reshape(h, 2, w, 2).mean(axis=(1, 3))
    out = np.zeros_like(premult)
    np.divide(premult, out_a[..., None], out=out, where=out_a[..., None] > 0)
    srgb = np.where(out <= 0.0031308, 12.92 * out, 1.055 * out ** (1 / 2.4) - 0.055)
    resolved = Framebuffer(w, h)
    resolved.color_buffer[..., :3] = np.floor(np.clip(srgb, 0, 1) * 255.0 + 0.5).astype(np.uint8)
    resolved.color_buffer[..., 3] = np.floor(out_a * 255.0 + 0.5).astype(np.uint8)
    resolved.depth_buffer[:] = frame.depth_buffer.reshape(h, 2, w, 2).min(axis=(1, 3))
    return resolved
