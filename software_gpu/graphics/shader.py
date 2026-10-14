"""
Programmable Vertex and Fragment Shaders and 3D Matrix Math for SoftwareGPU.
Implements standard GPU pipeline shading stages.
"""

from dataclasses import dataclass
from typing import Tuple, Optional
import numpy as np
import math


@dataclass
class Vertex:
    """Input vertex attribute data."""
    position: np.ndarray  # [x, y, z] or [x, y, z, 1]
    normal: np.ndarray = None  # [nx, ny, nz]
    uv: np.ndarray = None  # [u, v]
    color: np.ndarray = None  # [r, g, b]

    def __post_init__(self):
        if len(self.position) == 3:
            self.position = np.array([self.position[0], self.position[1], self.position[2], 1.0], dtype=np.float32)
        else:
            self.position = np.array(self.position, dtype=np.float32)

        if self.normal is None:
            self.normal = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        else:
            self.normal = np.array(self.normal, dtype=np.float32)

        if self.uv is None:
            self.uv = np.array([0.0, 0.0], dtype=np.float32)
        else:
            self.uv = np.array(self.uv, dtype=np.float32)

        if self.color is None:
            self.color = np.array([1.0, 1.0, 1.0], dtype=np.float32)
        else:
            self.color = np.array(self.color, dtype=np.float32)


# =====================================================================
# Matrix Transformations (Model, View, Projection)
# =====================================================================

class Matrix4:
    @staticmethod
    def identity() -> np.ndarray:
        return np.eye(4, dtype=np.float32)

    @staticmethod
    def translation(tx: float, ty: float, tz: float) -> np.ndarray:
        m = np.eye(4, dtype=np.float32)
        m[0, 3] = tx
        m[1, 3] = ty
        m[2, 3] = tz
        return m

    @staticmethod
    def scale(sx: float, sy: float, sz: float) -> np.ndarray:
        m = np.eye(4, dtype=np.float32)
        m[0, 0] = sx
        m[1, 1] = sy
        m[2, 2] = sz
        return m

    @staticmethod
    def rotation_x(rad: float) -> np.ndarray:
        c, s = np.cos(rad), np.sin(rad)
        m = np.eye(4, dtype=np.float32)
        m[1, 1], m[1, 2] = c, -s
        m[2, 1], m[2, 2] = s, c
        return m

    @staticmethod
    def rotation_y(rad: float) -> np.ndarray:
        c, s = np.cos(rad), np.sin(rad)
        m = np.eye(4, dtype=np.float32)
        m[0, 0], m[0, 2] = c, s
        m[2, 0], m[2, 2] = -s, c
        return m

    @staticmethod
    def rotation_z(rad: float) -> np.ndarray:
        c, s = np.cos(rad), np.sin(rad)
        m = np.eye(4, dtype=np.float32)
        m[0, 0], m[0, 1] = c, -s
        m[1, 0], m[1, 1] = s, c
        return m

    @staticmethod
    def perspective(fov_rad: float, aspect: float, near: float, far: float) -> np.ndarray:
        tan_half = np.tan(fov_rad / 2.0)
        m = np.zeros((4, 4), dtype=np.float32)
        m[0, 0] = 1.0 / (aspect * tan_half)
        m[1, 1] = 1.0 / tan_half
        m[2, 2] = -(far + near) / (far - near)
        m[2, 3] = -(2.0 * far * near) / (far - near)
        m[3, 2] = -1.0
        return m

    @staticmethod
    def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
        f = (target - eye).astype(np.float32)
        f /= np.linalg.norm(f)

        u = up.astype(np.float32)
        u /= np.linalg.norm(u)

        s = np.cross(f, u)
        s /= np.linalg.norm(s)

        u = np.cross(s, f)

        m = np.eye(4, dtype=np.float32)
        m[0, 0:3] = s
        m[1, 0:3] = u
        m[2, 0:3] = -f
        m[0, 3] = -np.dot(s, eye)
        m[1, 3] = -np.dot(u, eye)
        m[2, 3] = np.dot(f, eye)
        return m


# =====================================================================
# Programmable Shader Pipeline
# =====================================================================

class Shader:
    """Base class for programmable vertex and fragment shaders."""
    def vertex_shader(self, vertex: Vertex) -> Tuple[np.ndarray, dict]:
        """Runs vertex stage: returns clip-space position [x, y, z, w] and varying attributes."""
        raise NotImplementedError

    def fragment_shader(self, varyings: dict) -> Tuple[int, int, int, int]:
        """Runs fragment stage: takes interpolated attributes, returns RGBA (0-255)."""
        raise NotImplementedError


class BlinnPhongShader(Shader):
    """Full 3D Blinn-Phong lighting shader (Ambient + Diffuse + Specular)."""
    def __init__(
        self,
        model_matrix: np.ndarray,
        view_matrix: np.ndarray,
        proj_matrix: np.ndarray,
        light_dir: np.ndarray = np.array([0.5, 0.8, 1.0], dtype=np.float32),
        light_color: np.ndarray = np.array([1.0, 1.0, 1.0], dtype=np.float32),
        ambient_color: np.ndarray = np.array([0.2, 0.25, 0.35], dtype=np.float32),
        diffuse_color: np.ndarray = np.array([0.2, 0.6, 0.9], dtype=np.float32),
        specular_color: np.ndarray = np.array([1.0, 1.0, 1.0], dtype=np.float32),
        shininess: float = 32.0,
        texture: Optional[np.ndarray] = None
    ):
        self.mvp = proj_matrix @ view_matrix @ model_matrix
        self.model = model_matrix
        self.normal_matrix = np.linalg.inv(model_matrix[:3, :3]).T
        
        self.light_dir = light_dir / np.linalg.norm(light_dir)
        self.light_color = light_color
        self.ambient_color = ambient_color
        self.diffuse_color = diffuse_color
        self.specular_color = specular_color
        self.shininess = shininess
        self.texture = texture
        # A single immutable cache record avoids mixed fields across threads.
        # light_dir is public/mutable: check its value before every lookup.
        self._view_dir = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        self._half_cache = None

    def vertex_shader(self, vertex: Vertex) -> Tuple[np.ndarray, dict]:
        # Clip-space position
        clip_pos = self.mvp @ vertex.position

        # World normal
        world_normal = self.normal_matrix @ vertex.normal
        norm_len = np.linalg.norm(world_normal)
        if norm_len > 1e-6:
            world_normal /= norm_len

        varyings = {
            'normal': world_normal,
            'uv': vertex.uv,
            'color': vertex.color,
        }
        return clip_pos, varyings

    vertex_preparation_equivalent_to = vertex_shader

    def fragment_shader(self, varyings: dict) -> Tuple[int, int, int, int]:
        normal = varyings['normal']
        n_len = np.linalg.norm(normal)
        if n_len > 1e-6:
            normal = normal / n_len

        nx, ny, nz = normal[0], normal[1], normal[2]

        # Base surface color (either from texture or vertex/material diffuse)
        base_color = self.diffuse_color
        # Read once per fragment, without storing mutable texture dimensions.
        texture = self.texture
        if texture is not None:
            # Preserve NumPy float32 promotion/rounding for exact texel selection.
            u, v = varyings['uv'][0], varyings['uv'][1]
            u = max(0.0, min(1.0, u))
            v = max(0.0, min(1.0, v))
            th, tw = texture.shape[0], texture.shape[1]
            tx = int(u * (tw - 1))
            ty = int(v * (th - 1))
            tex_sample = texture[ty, tx, :3] / 255.0
            base_color = tex_sample

        # Diffuse component (Lambertian)
        ldx, ldy, ldz = float(self.light_dir[0]), float(self.light_dir[1]), float(self.light_dir[2])
        # Performance optimization: Replace np.dot with scalar multiplication.
        # Expected to reduce function call overhead during per-pixel operations.
        diff = max(0.0, float(nx*ldx + ny*ldy + nz*ldz))

        # Performance optimization: Explicitly cast float multiplier `diff` to np.float32
        # to prevent automatic silent promotion to float64 that degrades memory and math speed.
        diffuse = base_color * self.light_color * np.float32(diff)

        # Ambient component
        ambient = base_color * self.ambient_color

        # Cache only loop-invariant halfway direction, preserving the same
        # NumPy float32 operations and dot/power/color evaluation as baseline.
        # A mutable light_dir must invalidate the value, not leave stale light.
        light_key = (ldx, ldy, ldz)
        cache = self._half_cache
        if cache is None or cache[0] != light_key:
            half_dir = self.light_dir + self._view_dir
            half_len = np.linalg.norm(half_dir)
            valid = bool(half_len > 1e-6)
            if valid:
                half_dir /= half_len
            cache = (light_key, half_dir, valid)
            self._half_cache = cache

        if cache[2]:
            hx, hy, hz = float(cache[1][0]), float(cache[1][1]), float(cache[1][2])
            spec_dot = max(0.0, float(nx*hx + ny*hy + nz*hz))
            spec = spec_dot ** self.shininess
        else:
            spec = 0.0

        specular = self.specular_color * self.light_color * np.float32(spec)

        final_rgb = ambient + diffuse + specular

        # Manually handle NaN behavior from scalar implementations like min/max.
        if math.isnan(final_rgb[0]) or math.isnan(final_rgb[1]) or math.isnan(final_rgb[2]):
            raise ValueError("NaN detected in output color")

        # Performance optimization: Replace np.clip with pure scalar equivalents
        # using min/max to reduce overhead, but checking for NaN above to maintain semantics.
        final_rgb = final_rgb * 255.0
        r = int(min(255.0, max(0.0, float(final_rgb[0]))))
        g = int(min(255.0, max(0.0, float(final_rgb[1]))))
        b = int(min(255.0, max(0.0, float(final_rgb[2]))))
        return r, g, b, 255
