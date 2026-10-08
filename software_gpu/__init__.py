"""
SoftwareGPU - A Complete Software GPU Execution Architecture on CPU.
Inspired by MCUDA, PoCL, Mesa llvmpipe, and Microsoft WARP research.
Includes DirectX 11, Gaming PC Anti-Aliasing (MSAA/FXAA), HDR Bloom,
VPS Governor, Android/Mobile IPC, MMORPG Physics, and External Tool Integrations.
"""

# Core & VPS Governor
from .core.device import VirtualGPU, DeviceProperties
from .core.memory import GPUMemoryManager, MemoryCopyKind, SharedMemoryBank
from .core.types import Dim3, ThreadContext, GPUArray
from .core.vps_governor import VPSHardwareGovernor, GovernorMode, governor

# Compute & SIMT
from .compute.executor import SIMTExecutor, KernelLaunchConfig
from .compute.compiler import cuda_kernel, gpu_kernel
from .compute.kernels import (
    matmul_tiled_simt_kernel,
    parallel_reduction_sum_kernel,
    conv2d_simt_kernel,
    VectorizedGPUKernels
)

# Graphics & Gaming PC Post-Processing
from .graphics.framebuffer import Framebuffer
from .graphics.shader import Vertex, Shader, BlinnPhongShader, Matrix4
from .graphics.rasterizer import SoftwareRasterizer
from .graphics.postprocess import (
    MSAAFramebuffer,
    MSAARasterizer,
    FXAAPass,
    GamingPostProcessing
)

# DirectX 11 (Direct3D 11)
from .directx.d3d11 import (
    D3D11CreateDeviceAndSwapChain,
    ID3D11Device,
    ID3D11DeviceContext,
    IDXGISwapChain,
    ID3D11Buffer,
    D3D11_BIND_FLAG,
    D3D11_PRIMITIVE_TOPOLOGY
)

# Mobile & Android
from .mobile.android_server import AndroidIPCServer
from .mobile.opengles import OpenGLES3, EGLContext

# CUDA Drop-in Runtime & Task Redirection
from .redirector.cuda_runtime import cuda
from .redirector.interceptor import GPURedirector, redirector

# Network Server & Clients
from .network.server import SoftwareGPUServer
from .network.dispatcher import GPUCommandDispatcher
from .clients.python_client import SoftwareGPUClient

# Integrations (MMORPG, Blender, Image Editor)
from .integrations.mmorpg.game_compute_adapter import GameComputeEngine
from .integrations.blender.blender_render_engine import StandaloneBlenderBridge
from .integrations.image_editor.image_filter_endpoint import ImageFilterPipeline

__version__ = "1.2.0"
__all__ = [
    # Core
    "VirtualGPU",
    "DeviceProperties",
    "GPUMemoryManager",
    "MemoryCopyKind",
    "SharedMemoryBank",
    "VPSHardwareGovernor",
    "GovernorMode",
    "governor",
    "Dim3",
    "ThreadContext",
    "GPUArray",
    
    # Compute
    "SIMTExecutor",
    "KernelLaunchConfig",
    "cuda_kernel",
    "gpu_kernel",
    "matmul_tiled_simt_kernel",
    "parallel_reduction_sum_kernel",
    "conv2d_simt_kernel",
    "VectorizedGPUKernels",
    
    # Graphics & Gaming PC
    "Framebuffer",
    "Vertex",
    "Shader",
    "BlinnPhongShader",
    "Matrix4",
    "SoftwareRasterizer",
    "MSAAFramebuffer",
    "MSAARasterizer",
    "FXAAPass",
    "GamingPostProcessing",
    
    # DirectX 11
    "D3D11CreateDeviceAndSwapChain",
    "ID3D11Device",
    "ID3D11DeviceContext",
    "IDXGISwapChain",
    "ID3D11Buffer",
    "D3D11_BIND_FLAG",
    "D3D11_PRIMITIVE_TOPOLOGY",
    
    # Mobile / Android
    "AndroidIPCServer",
    "OpenGLES3",
    "EGLContext",
    
    # CUDA Drop-in
    "cuda",
    "GPURedirector",
    "redirector",
    
    # Network & Clients
    "SoftwareGPUServer",
    "GPUCommandDispatcher",
    "SoftwareGPUClient",
    
    # Integrations
    "GameComputeEngine",
    "StandaloneBlenderBridge",
    "ImageFilterPipeline"
]
