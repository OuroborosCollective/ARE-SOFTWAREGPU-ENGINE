"""
Blender Render Engine Addon and Standalone Bridge.
"""

from .blender_render_engine import StandaloneBlenderBridge

try:
    from .blender_render_engine import SoftwareGPURenderEngine, register, unregister
    __all__ = ["StandaloneBlenderBridge", "SoftwareGPURenderEngine", "register", "unregister"]
except ImportError:
    __all__ = ["StandaloneBlenderBridge"]
