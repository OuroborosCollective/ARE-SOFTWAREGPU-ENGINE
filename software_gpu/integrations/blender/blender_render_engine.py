"""
Blender Add-on and Custom Render Engine for SoftwareGPU.
Implements bpy.types.RenderEngine to offload Blender render passes to SoftwareGPU.
Supports both in-Blender execution and standalone batch render mode.
"""

import sys
import numpy as np

# Blender Add-on metadata
bl_info = {
    "name": "SoftwareGPU Render Engine",
    "author": "SoftwareGPU Team",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "Render Properties > Engine > SoftwareGPU",
    "description": "CPU-based Software GPU Render Engine for systems without physical GPUs.",
    "category": "Render",
}

try:
    import bpy
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Vertex, BlinnPhongShader, Matrix4
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.core.device import VirtualGPU


class StandaloneBlenderBridge:
    """Provides scene extraction and rendering for Blender scenes or standalone geometry."""
    def __init__(self, width: int = 640, height: int = 480):
        self.width = width
        self.height = height
        self.device = VirtualGPU.get_current_device()

    def render_scene(
        self,
        vertices: list,
        indices: list,
        camera_eye: np.ndarray,
        camera_target: np.ndarray,
        fov_deg: float = 45.0,
        light_pos: np.ndarray = np.array([2.0, 3.0, 4.0], dtype=np.float32),
        output_filepath: str = "/workspace/blender_software_gpu_render.bmp"
    ) -> Framebuffer:
        """Executes full SoftwareGPU rasterization pipeline for Blender scene datablocks."""
        fb = Framebuffer(self.width, self.height)
        fb.clear(r=30, g=34, b=42, a=255, depth=1.0)

        model = Matrix4.identity()
        view = Matrix4.look_at(
            eye=camera_eye,
            target=camera_target,
            up=np.array([0.0, 1.0, 0.0], dtype=np.float32)
        )
        proj = Matrix4.perspective(
            fov_rad=np.radians(fov_deg),
            aspect=float(self.width) / float(self.height),
            near=0.1,
            far=100.0
        )

        shader = BlinnPhongShader(
            model_matrix=model,
            view_matrix=view,
            proj_matrix=proj,
            light_dir=light_pos,
            diffuse_color=np.array([0.8, 0.4, 0.2], dtype=np.float32)
        )

        rasterizer = SoftwareRasterizer(fb)
        rasterizer.draw_mesh(vertices, indices, shader)

        if output_filepath:
            fb.save_bmp(output_filepath)

        return fb


if BLENDER_AVAILABLE:
    class SoftwareGPURenderEngine(bpy.types.RenderEngine):
        bl_idname = "SOFTWARE_GPU"
        bl_label = "SoftwareGPU (CPU Render Engine)"
        bl_use_preview = True

        def render(self, depsgraph):
            scene = depsgraph.scene
            scale = scene.render.resolution_percentage / 100.0
            width = int(scene.render.resolution_x * scale)
            height = int(scene.render.resolution_y * scale)

            bridge = StandaloneBlenderBridge(width, height)
            
            # Extract mesh vertices from Blender depsgraph
            mesh_verts = []
            mesh_indices = []
            for obj in depsgraph.objects:
                if obj.type == 'MESH':
                    mesh = obj.to_mesh()
                    for v in mesh.vertices:
                        mesh_verts.append(Vertex(
                            position=np.array([v.co.x, v.co.y, v.co.z], dtype=np.float32),
                            normal=np.array([v.normal.x, v.normal.y, v.normal.z], dtype=np.float32)
                        ))
                    for poly in mesh.polygons:
                        if len(poly.vertices) >= 3:
                            mesh_indices.append((poly.vertices[0], poly.vertices[1], poly.vertices[2]))
                    obj.to_mesh_clear()

            # Camera
            cam = scene.camera
            eye = np.array([cam.location.x, cam.location.y, cam.location.z], dtype=np.float32) if cam else np.array([0, 0, 5], dtype=np.float32)
            target = np.array([0, 0, 0], dtype=np.float32)

            fb = bridge.render_scene(mesh_verts, mesh_indices, eye, target, output_filepath=None)

            # Pass rendered pixels back to Blender's RenderResult
            result = self.begin_result(0, 0, width, height)
            layer = result.layers[0].passes["Combined"]
            # Convert RGBA uint8 to normalized float32
            normalized_rgba = fb.color_buffer[::-1].astype(np.float32) / 255.0
            layer.rect = normalized_rgba.reshape(-1, 4)
            self.end_result(result)


def register():
    if BLENDER_AVAILABLE:
        bpy.utils.register_class(SoftwareGPURenderEngine)


def unregister():
    if BLENDER_AVAILABLE:
        bpy.utils.unregister_class(SoftwareGPURenderEngine)


if __name__ == "__main__":
    # Test standalone execution
    bridge = StandaloneBlenderBridge(width=320, height=240)
    # Simple pyramid mesh
    verts = [
        Vertex(np.array([ 0.0,  1.0,  0.0]), np.array([0, 1, 0]), color=np.array([1, 0, 0])),
        Vertex(np.array([-1.0, -1.0,  1.0]), np.array([-1, -1, 1]), color=np.array([0, 1, 0])),
        Vertex(np.array([ 1.0, -1.0,  1.0]), np.array([1, -1, 1]), color=np.array([0, 0, 1])),
        Vertex(np.array([ 1.0, -1.0, -1.0]), np.array([1, -1, -1]), color=np.array([1, 1, 0])),
        Vertex(np.array([-1.0, -1.0, -1.0]), np.array([-1, -1, -1]), color=np.array([1, 0, 1])),
    ]
    indices = [
        (0, 1, 2),  # Front
        (0, 2, 3),  # Right
        (0, 3, 4),  # Back
        (0, 4, 1),  # Left
    ]
    fb = bridge.render_scene(
        verts, indices,
        camera_eye=np.array([0.0, 1.0, 3.5], dtype=np.float32),
        camera_target=np.array([0.0, 0.0, 0.0], dtype=np.float32)
    )
    print("Blender standalone bridge rendered test scene successfully to /workspace/blender_software_gpu_render.bmp")
