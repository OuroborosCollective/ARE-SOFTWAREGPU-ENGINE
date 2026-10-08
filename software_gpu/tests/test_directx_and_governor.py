"""
Unit Tests for DirectX 11 Pipeline and VPS Hardware Governor.
NO MOCKS, NO STUBS - real Direct3D 11 draw calls and real system profiling.
"""

import unittest
import numpy as np
import os
import tempfile

from software_gpu.directx.d3d11 import (
    D3D11CreateDeviceAndSwapChain,
    D3D11_BIND_FLAG,
    D3D11_PRIMITIVE_TOPOLOGY
)
from software_gpu.core.vps_governor import VPSHardwareGovernor, GovernorMode
from software_gpu.graphics.shader import Matrix4, Vertex


class TestDirectXAndGovernor(unittest.TestCase):
    def test_vps_governor_detection(self):
        """Test VPS CPU core detection, cgroups inspection, and safe concurrency calculation."""
        gov = VPSHardwareGovernor(mode=GovernorMode.VPS_SAFE)
        report = gov.get_status_report()

        self.assertGreater(report["effective_cpu_cores"], 0)
        self.assertGreater(report["recommended_safe_workers"], 0)
        self.assertLessEqual(report["recommended_safe_workers"], report["effective_cpu_cores"])
        self.assertIn("headroom_percentage", report)

    def test_directx11_pipeline_execution(self):
        """Test Direct3D 11 device creation, buffer binding, DrawIndexed, and DXGI Present."""
        width, height = 160, 120
        device, context, swap_chain = D3D11CreateDeviceAndSwapChain(width, height)

        vertices = np.array([
            [-0.5, -0.5, 0.5,  0.0, 0.0, 1.0,  1.0, 0.0, 0.0],
            [ 0.5, -0.5, 0.5,  0.0, 0.0, 1.0,  0.0, 1.0, 0.0],
            [ 0.0,  0.5, 0.5,  0.0, 0.0, 1.0,  0.0, 0.0, 1.0],
        ], dtype=np.float32)

        indices = np.array([0, 1, 2], dtype=np.uint32)

        vb = device.CreateBuffer(vertices, D3D11_BIND_FLAG.VERTEX_BUFFER)
        ib = device.CreateBuffer(indices, D3D11_BIND_FLAG.INDEX_BUFFER)
        cb = device.CreateBuffer(Matrix4.identity(), D3D11_BIND_FLAG.CONSTANT_BUFFER)

        context.ClearRenderTargetView((0.1, 0.1, 0.1, 1.0))
        context.ClearDepthStencilView(1.0)
        context.IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY.TRIANGLELIST)
        context.IASetVertexBuffers(0, vb)
        context.IASetIndexBuffer(ib)
        context.VSSetConstantBuffers(0, cb)

        # DrawIndexed execution
        context.DrawIndexed(len(indices))
        swap_chain.Present()

        # Verify pixel color was rendered into the front buffer
        center_color = swap_chain.front_buffer.color_buffer[60, 80]
        # At least one color channel should be non-background
        self.assertTrue(center_color[0] > 30 or center_color[1] > 30 or center_color[2] > 30)

        # Verify frame export
        with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as f:
            tmp_path = f.name
        try:
            swap_chain.SaveFrame(tmp_path)
            self.assertTrue(os.path.exists(tmp_path))
            self.assertGreater(os.path.getsize(tmp_path), 54)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
