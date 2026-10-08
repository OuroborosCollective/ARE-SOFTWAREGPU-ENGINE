"""
OpenGL ES 3.0 & EGL Interface for Android / Mobile on SoftwareGPU.
Emulates mobile graphics contexts (EGL) and draw calls (GLES3) on CPU.
"""

from typing import Tuple, List, Optional
import numpy as np

from ..graphics.framebuffer import Framebuffer
from ..graphics.shader import Vertex, Shader, BlinnPhongShader, Matrix4
from ..graphics.rasterizer import SoftwareRasterizer


class EGLContext:
    def __init__(self, width: int = 400, height: int = 300):
        self.width = width
        self.height = height
        self.framebuffer = Framebuffer(width, height)
        self.clear_color = (0.0, 0.0, 0.0, 1.0)
        self.viewport = (0, 0, width, height)
        self.rasterizer = SoftwareRasterizer(self.framebuffer)


class OpenGLES3:
    """OpenGL ES 3.0 API state machine."""
    GL_COLOR_BUFFER_BIT = 0x00004000
    GL_DEPTH_BUFFER_BIT = 0x00000100
    GL_TRIANGLES = 0x0004

    def __init__(self, ctx: Optional[EGLContext] = None):
        self.ctx = ctx or EGLContext()

    def glViewport(self, x: int, y: int, width: int, height: int) -> None:
        self.ctx.viewport = (x, y, width, height)

    def glClearColor(self, red: float, green: float, blue: float, alpha: float) -> None:
        self.ctx.clear_color = (red, green, blue, alpha)

    def glClear(self, mask: int) -> None:
        r, g, b, a = self.ctx.clear_color
        self.ctx.framebuffer.clear(
            int(r * 255), int(g * 255), int(b * 255), int(a * 255), depth=1.0
        )

    def glDrawArrays(self, mode: int, first: int, count: int, vertices: List[Vertex], shader: Shader) -> None:
        if mode == self.GL_TRIANGLES:
            indices = []
            for i in range(first, first + count, 3):
                if i + 2 < len(vertices):
                    indices.append((i, i + 1, i + 2))
            self.ctx.rasterizer.draw_mesh(vertices, indices, shader)

    def eglSwapBuffers(self, output_path: Optional[str] = None) -> None:
        if output_path:
            self.ctx.framebuffer.save_bmp(output_path)
