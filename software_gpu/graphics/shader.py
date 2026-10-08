"""
Programmable Vertex and Fragment Shaders and 3D Matrix Math for SoftwareGPU.
Implements standard GPU pipeline shading stages.
"""

from dataclasses import dataclass
from typing import Tuple, Optional
import numpy as np


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

    def fragment_shader(self, varyings: dict) -> Tuple[int, int, int, int]:
        normal = varyings['normal']
        n_len = np.linalg.norm(normal)
        if n_len > 1e-6:
            normal = normal / n_len

        # Base surface color (either from texture or vertex/material diffuse)
        base_color = self.diffuse_color
        if self.texture is not None:
            u, v = varyings['uv'][0], varyings['uv'][1]
            u = max(0.0, min(1.0, u))
            v = max(0.0, min(1.0, v))
            th, tw = self.texture.shape[0], self.texture.shape[1]
            tx = int(u * (tw - 1))
            ty = int(v * (th - 1))
            tex_sample = self.texture[ty, tx, :3] / 255.0
            base_color = tex_sample

        # Diffuse component (Lambertian)
        diff = max(0.0, float(np.dot(normal, self.light_dir)))
        diffuse = base_color * self.light_color * diff

        # Ambient component
        ambient = base_color * self.ambient_color

        # Specular component (Blinn-Phong halfway vector)
        view_dir = np.array([0.0, 0.0, 1.0], dtype=np.float32)  # In camera space looking towards +z
        half_dir = (self.light_dir + view_dir)
        half_len = np.linalg.norm(half_dir)
        if half_len > 1e-6:
            half_dir /= half_len
            spec = max(0.0, float(np.dot(normal, half_dir))) ** self.shininess
        else:
            spec = 0.0
        specular = self.specular_color * self.light_color * spec

        final_rgb = np.clip(ambient + diffuse + specular, 0.0, 1.0) * 255.0
        return int(final_rgb[0]), int(final_rgb[1]), int(final_rgb[2]), 255
