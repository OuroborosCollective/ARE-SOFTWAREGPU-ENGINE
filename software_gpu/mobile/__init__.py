"""
Mobile & Android Subsystem for SoftwareGPU.
Supports Unix Domain Sockets, Android Abstract Namespace, and OpenGL ES 3.0 / EGL.
"""

from .android_server import AndroidIPCServer
from .opengles import OpenGLES3, EGLContext

__all__ = [
    "AndroidIPCServer",
    "OpenGLES3",
    "EGLContext"
]
