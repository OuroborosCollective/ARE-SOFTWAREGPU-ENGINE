"""
Unit Tests for Modern Gaming PC Features (MSAA, FXAA, HDR Bloom)
and Android Mobile IPC / OpenGL ES 3.0.
NO MOCKS, NO STUBS - executes real pixel buffers and real Unix Domain Sockets.
"""

import unittest
import numpy as np
import time
import os
import socket

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Vertex, BlinnPhongShader, Matrix4
from software_gpu.graphics.postprocess import (
    MSAAFramebuffer,
    MSAARasterizer,
    FXAAPass,
    GamingPostProcessing
)
from software_gpu.mobile.android_server import AndroidIPCServer
from software_gpu.mobile.opengles import OpenGLES3, EGLContext
from software_gpu.network.protocol import pack_message, unpack_header, MsgType, HEADER_SIZE


class TestGamingAndMobile(unittest.TestCase):
    def test_msaa_resolve_smooths_edges(self):
        """Test that 4x MSAA sub-pixel sampling resolves into smooth pixels."""
        msaa_fb = MSAAFramebuffer(64, 64, samples=4)
        msaa_fb.clear(0, 0, 0, 255, 1.0)

        # Triangle covering only half of a pixel's sub-samples
        verts = [
            Vertex(np.array([-0.8, -0.8, 0.5]), color=np.array([1, 1, 1])),
            Vertex(np.array([ 0.8, -0.8, 0.5]), color=np.array([1, 1, 1])),
            Vertex(np.array([ 0.0,  0.8, 0.5]), color=np.array([1, 1, 1])),
        ]
        indices = [(0, 1, 2)]

        model = Matrix4.identity()
        view = Matrix4.look_at(np.array([0, 0, 2]), np.array([0, 0, 0]), np.array([0, 1, 0]))
        proj = Matrix4.perspective(np.radians(60.0), 1.0, 0.1, 10.0)
        shader = BlinnPhongShader(model, view, proj, diffuse_color=np.array([1.0, 1.0, 1.0]))

        rast = MSAARasterizer(msaa_fb)
        rast.draw_mesh(verts, indices, shader)

        resolved = msaa_fb.resolve()
        self.assertEqual(resolved.width, 64)
        self.assertEqual(resolved.height, 64)

        # Pixels on the boundary should have intermediate values (not just 0 or 255)
        boundary_colors = resolved.color_buffer[..., 0]
        intermediate_pixels = np.count_nonzero((boundary_colors > 20) & (boundary_colors < 235))
        self.assertGreater(intermediate_pixels, 0, "MSAA must create smooth intermediate anti-aliased edge values!")

    def test_fxaa_filter(self):
        """Test FXAA post-processing filter."""
        fb = Framebuffer(64, 64)
        fb.clear(0, 0, 0, 255, 1.0)
        # Create a sharp black/white high-contrast vertical line
        fb.color_buffer[:, 32:, :3] = 255

        fxaa_fb = FXAAPass.apply(fb, edge_threshold=0.05)
        # Line boundary at x=31/32 should now be blended
        val_31 = int(fxaa_fb.color_buffer[30, 31, 0])
        val_32 = int(fxaa_fb.color_buffer[30, 32, 0])
        self.assertGreater(val_31, 0, "FXAA should soften edge at adjacent pixel")
        self.assertLess(val_32, 255, "FXAA should soften edge at edge pixel")

    def test_hdr_bloom_and_aces(self):
        """Test HDR Bloom and ACES tone mapping."""
        fb = Framebuffer(64, 64)
        fb.clear(10, 10, 10, 255, 1.0)
        # Super bright center pixel
        fb.color_buffer[32, 32, :3] = 255

        hdr_fb = GamingPostProcessing.apply_bloom_and_hdr(fb, bloom_threshold=0.5, bloom_intensity=0.8)
        # Neighboring pixels should now have bloom glow
        glow_val = int(hdr_fb.color_buffer[32, 33, 0])
        self.assertGreater(glow_val, 10, "Bloom glow must bleed onto neighboring pixels")

    @unittest.skipUnless(os.name == "posix" and hasattr(socket, "AF_UNIX"),
                         "Linux/Android POSIX Unix-domain-socket test; unsupported on Windows")
    def test_android_unix_domain_socket_ipc(self):
        """Test Android UDS / LocalSocket IPC server and client communication."""
        sock_path = "/tmp/test_android_gpu.sock"
        server = AndroidIPCServer(socket_path=sock_path, abstract_name="test_soft_gpu")
        server.start()
        time.sleep(0.05)

        # Connect via Unix Domain Socket
        client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_sock.connect(sock_path)

        req_payload = {"method": "device_info", "params": {}, "id": 42}
        client_sock.sendall(pack_message(MsgType.JSON_REQUEST, req_payload))

        header = client_sock.recv(HEADER_SIZE)
        msg_type, flags, length = unpack_header(header)
        body = client_sock.recv(length)
        import json
        resp = json.loads(body.decode("utf-8"))

        self.assertIn("result", resp)
        self.assertIn("name", resp["result"])
        client_sock.close()
        server.stop()

    def test_opengles_mobile_context(self):
        """Test OpenGL ES 3.0 / EGL mobile graphics interface."""
        ctx = EGLContext(80, 60)
        gles = OpenGLES3(ctx)
        gles.glViewport(0, 0, 80, 60)
        gles.glClearColor(0.2, 0.4, 0.6, 1.0)
        gles.glClear(OpenGLES3.GL_COLOR_BUFFER_BIT | OpenGLES3.GL_DEPTH_BUFFER_BIT)

        self.assertEqual(int(ctx.framebuffer.color_buffer[30, 40, 0]), int(0.2 * 255))
        self.assertEqual(int(ctx.framebuffer.color_buffer[30, 40, 1]), int(0.4 * 255))
        self.assertEqual(int(ctx.framebuffer.color_buffer[30, 40, 2]), int(0.6 * 255))


if __name__ == "__main__":
    unittest.main()
