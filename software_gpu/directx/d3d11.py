"""
DirectX 11 (Direct3D 11) API and Pipeline Implementation for SoftwareGPU.
Modeled after Microsoft WARP (Windows Advanced Rasterization Platform) and Mesa D3D12.
Provides ID3D11Device, ID3D11DeviceContext, IDXGISwapChain, and shader pipeline.
"""

from typing import Tuple, List, Dict, Any, Optional, Callable
import numpy as np

from ..graphics.framebuffer import Framebuffer
from ..graphics.shader import Vertex, Shader, BlinnPhongShader, Matrix4
from ..graphics.rasterizer import SoftwareRasterizer
from ..core.device import VirtualGPU


# =====================================================================
# DirectX Constants and Flags
# =====================================================================

class D3D11_BIND_FLAG:
    VERTEX_BUFFER = 0x1
    INDEX_BUFFER = 0x2
    CONSTANT_BUFFER = 0x4
    SHADER_RESOURCE = 0x8
    RENDER_TARGET = 0x20
    DEPTH_STENCIL = 0x40


class D3D11_PRIMITIVE_TOPOLOGY:
    UNDEFINED = 0
    POINTLIST = 1
    LINELIST = 2
    LINESTRIP = 3
    TRIANGLELIST = 4
    TRIANGLESTRIP = 5


class D3D11_VIEWPORT:
    def __init__(self, top_left_x: float = 0.0, top_left_y: float = 0.0, width: float = 800.0, height: float = 600.0, min_depth: float = 0.0, max_depth: float = 1.0):
        self.TopLeftX = top_left_x
        self.TopLeftY = top_left_y
        self.Width = width
        self.Height = height
        self.MinDepth = min_depth
        self.MaxDepth = max_depth


# =====================================================================
# Direct3D Resource Objects
# =====================================================================

class ID3D11Resource:
    pass


class ID3D11Buffer(ID3D11Resource):
    """Encapsulates a Direct3D 11 GPU Buffer (Vertex, Index, or Constant buffer)."""
    def __init__(self, data: np.ndarray, bind_flags: int):
        self.data = np.ascontiguousarray(data)
        self.bind_flags = bind_flags
        self.byte_width = self.data.nbytes


class ID3D11VertexShader:
    """Represents a Direct3D 11 Vertex Shader program."""
    def __init__(self, shader_func: Optional[Callable] = None):
        self.shader_func = shader_func


class ID3D11PixelShader:
    """Represents a Direct3D 11 Pixel / Fragment Shader program."""
    def __init__(self, shader_func: Optional[Callable] = None):
        self.shader_func = shader_func


class ID3D11InputLayout:
    """Describes vertex struct element layout for the Input Assembler."""
    def __init__(self, layout_elements: List[Dict[str, Any]]):
        self.layout_elements = layout_elements


# =====================================================================
# SwapChain (DXGI)
# =====================================================================

class IDXGISwapChain:
    """DXGI SwapChain managing front and back buffers."""
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.back_buffer = Framebuffer(width, height)
        self.front_buffer = Framebuffer(width, height)
        self.frame_count = 0

    def Present(self, sync_interval: int = 0, flags: int = 0) -> None:
        """Presents rendered frame by swapping buffers."""
        self.front_buffer.color_buffer[...] = self.back_buffer.color_buffer[...]
        self.front_buffer.depth_buffer[...] = self.back_buffer.depth_buffer[...]
        self.frame_count += 1

    def SaveFrame(self, file_path: str) -> None:
        """Saves current presented frame as BMP file."""
        self.front_buffer.save_bmp(file_path)


# =====================================================================
# Device Context (Pipeline State & Command Executor)
# =====================================================================

class ID3D11DeviceContext:
    """Direct3D 11 Pipeline Context. Handles pipeline bindings and Draw calls."""
    def __init__(self, device: 'ID3D11Device'):
        self.device = device
        self.swap_chain: Optional[IDXGISwapChain] = None
        self.current_fb: Optional[Framebuffer] = None

        # Input Assembler (IA) stage
        self.input_layout: Optional[ID3D11InputLayout] = None
        self.vertex_buffer: Optional[ID3D11Buffer] = None
        self.index_buffer: Optional[ID3D11Buffer] = None
        self.topology: int = D3D11_PRIMITIVE_TOPOLOGY.TRIANGLELIST

        # Vertex Shader (VS) stage
        self.vertex_shader: Optional[ID3D11VertexShader] = None
        self.vs_constant_buffers: Dict[int, ID3D11Buffer] = {}

        # Rasterizer (RS) stage
        self.viewport = D3D11_VIEWPORT()

        # Pixel Shader (PS) stage
        self.pixel_shader: Optional[ID3D11PixelShader] = None
        self.ps_constant_buffers: Dict[int, ID3D11Buffer] = {}

    def IASetInputLayout(self, layout: ID3D11InputLayout) -> None:
        self.input_layout = layout

    def IASetVertexBuffers(self, start_slot: int, buffer: ID3D11Buffer, stride: int = 0, offset: int = 0) -> None:
        self.vertex_buffer = buffer

    def IASetIndexBuffer(self, buffer: ID3D11Buffer, format_type: str = "uint32", offset: int = 0) -> None:
        self.index_buffer = buffer

    def IASetPrimitiveTopology(self, topology: int) -> None:
        self.topology = topology

    def VSSetShader(self, shader: ID3D11VertexShader) -> None:
        self.vertex_shader = shader

    def VSSetConstantBuffers(self, start_slot: int, buffer: ID3D11Buffer) -> None:
        self.vs_constant_buffers[start_slot] = buffer

    def RSSetViewports(self, viewport: D3D11_VIEWPORT) -> None:
        self.viewport = viewport

    def PSSetShader(self, shader: ID3D11PixelShader) -> None:
        self.pixel_shader = shader

    def PSSetConstantBuffers(self, start_slot: int, buffer: ID3D11Buffer) -> None:
        self.ps_constant_buffers[start_slot] = buffer

    def ClearRenderTargetView(self, color_rgba: Tuple[float, float, float, float] = (0.1, 0.1, 0.15, 1.0)) -> None:
        if self.current_fb:
            r = int(color_rgba[0] * 255)
            g = int(color_rgba[1] * 255)
            b = int(color_rgba[2] * 255)
            a = int(color_rgba[3] * 255)
            self.current_fb.clear(r, g, b, a, 1.0)

    def ClearDepthStencilView(self, depth: float = 1.0) -> None:
        if self.current_fb:
            self.current_fb.depth_buffer.fill(depth)

    def DrawIndexed(self, index_count: int, start_index_location: int = 0, base_vertex_location: int = 0) -> None:
        """Executes DrawIndexed command through the SoftwareGPU rasterization pipeline."""
        if not self.vertex_buffer or not self.index_buffer or not self.current_fb:
            return

        vb_data = self.vertex_buffer.data
        ib_data = self.index_buffer.data

        # Construct vertex attribute list
        vertices = []
        for i in range(len(vb_data)):
            row = vb_data[i]
            pos = row[:3]
            norm = row[3:6] if len(row) >= 6 else np.array([0, 0, 1], dtype=np.float32)
            col = row[6:9] if len(row) >= 9 else np.array([1, 1, 1], dtype=np.float32)
            vertices.append(Vertex(pos, norm, color=col))

        indices = []
        for i in range(0, index_count, 3):
            indices.append((int(ib_data[i]), int(ib_data[i + 1]), int(ib_data[i + 2])))

        # Extract MVP matrix from constant buffer 0 if bound
        mvp = Matrix4.identity()
        if 0 in self.vs_constant_buffers:
            mvp = self.vs_constant_buffers[0].data

        # Shader bridge
        class D3D11ShaderBridge(Shader):
            def __init__(self, mvp_mat, vs_fn, ps_fn):
                self.mvp = mvp_mat
                self.vs_fn = vs_fn
                self.ps_fn = ps_fn

            def vertex_shader(self, v: Vertex) -> Tuple[np.ndarray, dict]:
                if self.vs_fn:
                    return self.vs_fn(v, self.mvp)
                clip = self.mvp @ v.position
                return clip, {"normal": v.normal, "color": v.color}

            def fragment_shader(self, varyings: dict) -> Tuple[int, int, int, int]:
                if self.ps_fn:
                    return self.ps_fn(varyings)
                c = varyings.get("color", np.array([1, 1, 1]))
                return int(c[0] * 255), int(c[1] * 255), int(c[2] * 255), 255

        bridge_shader = D3D11ShaderBridge(
            mvp,
            self.vertex_shader.shader_func if self.vertex_shader else None,
            self.pixel_shader.shader_func if self.pixel_shader else None
        )

        rasterizer = SoftwareRasterizer(self.current_fb)
        rasterizer.draw_mesh(vertices, indices, bridge_shader)


# =====================================================================
# Direct3D 11 Device
# =====================================================================

class ID3D11Device:
    """Direct3D 11 Device factory for resources."""
    def __init__(self):
        self.virtual_gpu = VirtualGPU.get_current_device()

    def CreateBuffer(self, data: np.ndarray, bind_flags: int) -> ID3D11Buffer:
        return ID3D11Buffer(data, bind_flags)

    def CreateVertexShader(self, shader_func: Optional[Callable] = None) -> ID3D11VertexShader:
        return ID3D11VertexShader(shader_func)

    def CreatePixelShader(self, shader_func: Optional[Callable] = None) -> ID3D11PixelShader:
        return ID3D11PixelShader(shader_func)

    def CreateInputLayout(self, layout_elements: List[Dict[str, Any]]) -> ID3D11InputLayout:
        return ID3D11InputLayout(layout_elements)


def D3D11CreateDeviceAndSwapChain(width: int = 800, height: int = 600) -> Tuple[ID3D11Device, ID3D11DeviceContext, IDXGISwapChain]:
    """Standard Direct3D 11 initialization factory."""
    device = ID3D11Device()
    context = ID3D11DeviceContext(device)
    swap_chain = IDXGISwapChain(width, height)
    context.swap_chain = swap_chain
    context.current_fb = swap_chain.back_buffer
    context.RSSetViewports(D3D11_VIEWPORT(0, 0, width, height))
    return device, context, swap_chain
