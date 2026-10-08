"""
DirectX 11 Execution Demo on SoftwareGPU.
Demonstrates standard Direct3D 11 pipeline setup, buffer creation, shader execution,
DrawIndexed command, and frame presentation.
"""

import os
import numpy as np
from software_gpu.directx.d3d11 import (
    D3D11CreateDeviceAndSwapChain,
    D3D11_BIND_FLAG,
    D3D11_PRIMITIVE_TOPOLOGY
)
from software_gpu.graphics.shader import Matrix4, Vertex


def main():
    print("=" * 70)
    print(" DirectX 11 (Direct3D 11) Execution on SoftwareGPU")
    print(" Architecture: CPU Software Rasterizer (WARP / llvmpipe Model)")
    print("=" * 70)

    width, height = 400, 300
    print(f"\n[1] Initializing Direct3D 11 Device, Context & DXGI SwapChain ({width}x{height})...")
    device, context, swap_chain = D3D11CreateDeviceAndSwapChain(width, height)

    # 3D Tetrahedron / Pyramid vertices: [x, y, z, nx, ny, nz, r, g, b]
    vertex_data = np.array([
        # Base vertices
        [-1.0, -0.6, -1.0,   0.0, -1.0,  0.0,   0.2, 0.8, 0.3],
        [ 1.0, -0.6, -1.0,   0.0, -1.0,  0.0,   0.8, 0.2, 0.3],
        [ 0.0, -0.6,  1.0,   0.0, -1.0,  0.0,   0.3, 0.4, 0.9],
        # Apex vertex
        [ 0.0,  1.0,  0.0,   0.0,  1.0,  0.0,   0.9, 0.7, 0.1],
    ], dtype=np.float32)

    # Index buffer for 4 triangle faces
    index_data = np.array([
        0, 1, 2,  # Bottom face
        0, 3, 1,  # Front-left face
        1, 3, 2,  # Front-right face
        2, 3, 0   # Back face
    ], dtype=np.uint32)

    print("[2] Creating Direct3D 11 Buffers (Vertex Buffer, Index Buffer)...")
    v_buffer = device.CreateBuffer(vertex_data, D3D11_BIND_FLAG.VERTEX_BUFFER)
    i_buffer = device.CreateBuffer(index_data, D3D11_BIND_FLAG.INDEX_BUFFER)

    # Model-View-Projection matrix in Constant Buffer 0
    model = Matrix4.rotation_y(np.radians(40.0)) @ Matrix4.rotation_x(np.radians(20.0))
    view = Matrix4.look_at(
        eye=np.array([0.0, 1.2, 3.5], dtype=np.float32),
        target=np.array([0.0, 0.0, 0.0], dtype=np.float32),
        up=np.array([0.0, 1.0, 0.0], dtype=np.float32)
    )
    proj = Matrix4.perspective(
        fov_rad=np.radians(50.0),
        aspect=float(width) / float(height),
        near=0.1,
        far=20.0
    )
    mvp = proj @ view @ model

    c_buffer = device.CreateBuffer(mvp, D3D11_BIND_FLAG.CONSTANT_BUFFER)

    # HLSL-style Vertex and Pixel Shaders
    def hlsl_vs(v: Vertex, mvp_matrix: np.ndarray):
        clip = mvp_matrix @ v.position
        # Simple directional lighting vector
        light_dir = np.array([0.5, 0.8, 1.0], dtype=np.float32)
        light_dir /= np.linalg.norm(light_dir)
        diff = max(0.2, float(np.dot(v.normal, light_dir)))
        lit_color = v.color * diff
        return clip, {"color": lit_color}

    def hlsl_ps(varyings: dict):
        col = varyings["color"]
        return int(col[0] * 255), int(col[1] * 255), int(col[2] * 255), 255

    vs = device.CreateVertexShader(hlsl_vs)
    ps = device.CreatePixelShader(hlsl_ps)

    print("[3] Binding Pipeline State & Shaders to Context...")
    context.ClearRenderTargetView((0.08, 0.10, 0.15, 1.0))
    context.ClearDepthStencilView(1.0)
    context.IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY.TRIANGLELIST)
    context.IASetVertexBuffers(0, v_buffer)
    context.IASetIndexBuffer(i_buffer)
    context.VSSetShader(vs)
    context.VSSetConstantBuffers(0, c_buffer)
    context.PSSetShader(ps)

    print("[4] Executing Direct3D 11 DrawIndexed command...")
    context.DrawIndexed(len(index_data))

    print("[5] Presenting frame via DXGI SwapChain...")
    swap_chain.Present()

    out_file = "/workspace/directx_software_gpu_render.bmp"
    swap_chain.SaveFrame(out_file)
    print(f"SUCCESS: DirectX 11 frame rendered and saved to: {out_file} (Size: {os.path.getsize(out_file):,} bytes)")


if __name__ == "__main__":
    main()
