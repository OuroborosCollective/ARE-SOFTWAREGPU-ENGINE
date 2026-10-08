"""
RPC Command Dispatcher for SoftwareGPU Network Service.
Executes incoming GPGPU and graphics tasks on the Virtual GPU.
"""

import math
import numpy as np
from typing import Dict, Any, Tuple

from ..core.device import VirtualGPU
from ..compute.kernels import VectorizedGPUKernels, conv2d_simt_kernel
from ..compute.compiler import cuda_kernel
from ..graphics.framebuffer import Framebuffer
from ..graphics.shader import Vertex, BlinnPhongShader, Matrix4
from ..graphics.rasterizer import SoftwareRasterizer
from .protocol import encode_tensor_base64, decode_tensor_base64


class GPUCommandDispatcher:
    """Dispatches remote API commands to the local Software GPU."""
    def __init__(self):
        self.device = VirtualGPU.get_current_device()

    def handle_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Routes a method call to its handler."""
        handler = getattr(self, f"op_{method}", None)
        if handler is None:
            raise ValueError(f"Unknown GPU method: {method}")
        return handler(params)

    def op_device_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Returns GPU device hardware properties and telemetry."""
        props = self.device.properties
        telemetry = self.device.get_telemetry()
        return {
            "name": props.name,
            "sm_count": props.multi_processor_count,
            "warp_size": props.warp_size,
            "total_vram_mb": props.total_global_mem // (1024 * 1024),
            "telemetry": telemetry
        }

    def op_gemm(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Matrix multiplication offload."""
        A = decode_tensor_base64(params["a"]) if "__tensor__" in params["a"] else np.array(params["a"], dtype=np.float32)
        B = decode_tensor_base64(params["b"]) if "__tensor__" in params["b"] else np.array(params["b"], dtype=np.float32)

        d_a = self.device.memory.to_device(A)
        d_b = self.device.memory.to_device(B)
        d_c = self.device.memory.allocate((A.shape[0], B.shape[1]), dtype=A.dtype)

        VectorizedGPUKernels.gemm_parallel(d_a, d_b, d_c)
        result = d_c.to_numpy()

        self.device.memory.free(d_a)
        self.device.memory.free(d_b)
        self.device.memory.free(d_c)

        return {"result": encode_tensor_base64(result)}

    def op_activation(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Tensor activation offload (ReLU, GELU)."""
        X = decode_tensor_base64(params["x"]) if "__tensor__" in params["x"] else np.array(params["x"], dtype=np.float32)
        act_type = params.get("type", "relu").lower()

        d_x = self.device.memory.to_device(X)
        d_out = self.device.memory.allocate(X.shape, dtype=X.dtype)

        if act_type == "relu":
            VectorizedGPUKernels.relu(d_x, d_out)
        elif act_type == "gelu":
            VectorizedGPUKernels.gelu(d_x, d_out)
        else:
            raise ValueError(f"Unsupported activation: {act_type}")

        result = d_out.to_numpy()
        self.device.memory.free(d_x)
        self.device.memory.free(d_out)

        return {"result": encode_tensor_base64(result)}

    def op_vector_add(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Vector addition offload."""
        A = decode_tensor_base64(params["a"]) if "__tensor__" in params["a"] else np.array(params["a"], dtype=np.float32)
        B = decode_tensor_base64(params["b"]) if "__tensor__" in params["b"] else np.array(params["b"], dtype=np.float32)

        d_a = self.device.memory.to_device(A)
        d_b = self.device.memory.to_device(B)
        d_c = self.device.memory.allocate(A.shape, dtype=A.dtype)

        VectorizedGPUKernels.vector_add(d_a, d_b, d_c)
        result = d_c.to_numpy()

        self.device.memory.free(d_a)
        self.device.memory.free(d_b)
        self.device.memory.free(d_c)

        return {"result": encode_tensor_base64(result)}

    def op_render_mesh(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Renders 3D mesh via SoftwareRasterizer and returns base64 BMP."""
        import base64
        width = int(params.get("width", 256))
        height = int(params.get("height", 256))
        verts_raw = params.get("vertices", [])
        indices = [tuple(tri) for tri in params.get("indices", [])]

        fb = Framebuffer(width, height)
        bg = params.get("clear_color", [20, 25, 35])
        fb.clear(bg[0], bg[1], bg[2], 255, 1.0)

        vertices = [
            Vertex(
                position=np.array(v["pos"], dtype=np.float32),
                normal=np.array(v.get("norm", [0, 0, 1]), dtype=np.float32),
                uv=np.array(v.get("uv", [0, 0]), dtype=np.float32),
                color=np.array(v.get("color", [1, 1, 1]), dtype=np.float32)
            )
            for v in verts_raw
        ]

        cam = params.get("camera", {})
        eye = np.array(cam.get("eye", [0, 0, 3]), dtype=np.float32)
        target = np.array(cam.get("target", [0, 0, 0]), dtype=np.float32)
        up = np.array(cam.get("up", [0, 1, 0]), dtype=np.float32)

        model = Matrix4.identity()
        view = Matrix4.look_at(eye, target, up)
        proj = Matrix4.perspective(np.radians(cam.get("fov", 45.0)), width / height, 0.1, 100.0)

        light_dir = np.array(params.get("light_dir", [1.0, 1.5, 2.0]), dtype=np.float32)
        shader = BlinnPhongShader(
            model, view, proj,
            light_dir=light_dir,
            diffuse_color=np.array(params.get("diffuse_color", [0.2, 0.7, 0.9]), dtype=np.float32)
        )

        rasterizer = SoftwareRasterizer(fb)
        rasterizer.draw_mesh(vertices, indices, shader)

        # Export to in-memory BMP
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as f:
            tmp_path = f.name
        try:
            fb.save_bmp(tmp_path)
            with open(tmp_path, "rb") as f:
                bmp_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        return {
            "width": width,
            "height": height,
            "format": "bmp",
            "image_b64": base64.b64encode(bmp_bytes).decode("ascii")
        }

    def op_physics_step(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """MMORPG Game physics / entity movement & boundary collision pass."""
        pos = decode_tensor_base64(params["positions"])
        vel = decode_tensor_base64(params["velocities"])
        dt = float(params.get("dt", 0.016))
        world_bounds = params.get("world_bounds", [-500.0, 500.0, -500.0, 500.0, 0.0, 200.0])

        # SIMD vectorized update: pos += vel * dt
        new_pos = pos + vel * dt

        # Boundary bounce / clamping
        for axis, (b_min, b_max) in enumerate([
            (world_bounds[0], world_bounds[1]),
            (world_bounds[2], world_bounds[3]),
            (world_bounds[4], world_bounds[5])
        ]):
            under = new_pos[:, axis] < b_min
            over = new_pos[:, axis] > b_max
            vel[under, axis] *= -0.8
            vel[over, axis] *= -0.8
            new_pos[under, axis] = b_min
            new_pos[over, axis] = b_max

        return {
            "positions": encode_tensor_base64(new_pos),
            "velocities": encode_tensor_base64(vel)
        }

    def op_boids_swarm(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """MMORPG NPC Swarm / Boids flocking simulation offload."""
        pos = decode_tensor_base64(params["positions"])
        vel = decode_tensor_base64(params["velocities"])
        dt = float(params.get("dt", 0.033))
        max_speed = float(params.get("max_speed", 10.0))

        # Vectorized center of mass attraction + dampening
        center = np.mean(pos, axis=0)
        to_center = center - pos
        dist = np.linalg.norm(to_center, axis=1, keepdims=True) + 1e-5
        accel = (to_center / dist) * 2.0

        new_vel = vel + accel * dt
        speeds = np.linalg.norm(new_vel, axis=1, keepdims=True) + 1e-5
        new_vel = np.where(speeds > max_speed, (new_vel / speeds) * max_speed, new_vel)
        new_pos = pos + new_vel * dt

        return {
            "positions": encode_tensor_base64(new_pos),
            "velocities": encode_tensor_base64(new_vel)
        }
