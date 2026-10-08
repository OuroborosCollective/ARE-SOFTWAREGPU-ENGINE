"""
Unit and Integration Tests for SoftwareGPU Network Service and Adapters.
Tests HTTP, TCP Socket, Node.js Client, MMORPG Compute, and Image Filters.
NO MOCKS, NO STUBS - executes real network traffic and real calculations.
"""

import unittest
import time
import os
import numpy as np

from software_gpu.network.server import SoftwareGPUServer
from software_gpu.clients.python_client import SoftwareGPUClient
from software_gpu.integrations.mmorpg.game_compute_adapter import GameComputeEngine
from software_gpu.integrations.image_editor.image_filter_endpoint import ImageFilterPipeline


class TestNetworkAndIntegrations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start SoftwareGPU server on test ports
        cls.http_port = 8188
        cls.tcp_port = 8189
        cls.server = SoftwareGPUServer(http_port=cls.http_port, tcp_port=cls.tcp_port)
        cls.server.start()
        time.sleep(0.1)  # Allow sockets to bind

        cls.http_client = SoftwareGPUClient(http_port=cls.http_port, tcp_port=cls.tcp_port, use_tcp=False)
        cls.tcp_client = SoftwareGPUClient(http_port=cls.http_port, tcp_port=cls.tcp_port, use_tcp=True)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_http_device_info(self):
        """Test querying device status via HTTP REST endpoint."""
        info = self.http_client.get_device_info()
        self.assertIn("Virtual-Software-GPU", info["name"])
        self.assertGreater(info["sm_count"], 0)
        self.assertGreater(info["total_vram_mb"], 0)

    def test_http_gemm_offload(self):
        """Test matrix multiplication offloaded via HTTP REST."""
        A = np.random.randn(32, 32).astype(np.float32)
        B = np.random.randn(32, 32).astype(np.float32)

        res = self.http_client.compute_gemm(A, B)
        expected = np.matmul(A, B)
        np.testing.assert_allclose(res, expected, rtol=1e-5, atol=1e-5)

    def test_tcp_gemm_offload(self):
        """Test matrix multiplication offloaded via High-Speed TCP Binary Socket."""
        A = np.random.randn(32, 32).astype(np.float32)
        B = np.random.randn(32, 32).astype(np.float32)

        res = self.tcp_client.compute_gemm(A, B)
        expected = np.matmul(A, B)
        np.testing.assert_allclose(res, expected, rtol=1e-5, atol=1e-5)

    def test_tcp_activation_relu(self):
        """Test ReLU activation offloaded via TCP Binary Socket."""
        X = np.array([-10.0, -2.0, 0.0, 5.0, 12.5], dtype=np.float32)
        res = self.tcp_client.compute_activation(X, act_type="relu")
        expected = np.maximum(X, 0.0)
        np.testing.assert_allclose(res, expected, rtol=1e-5, atol=1e-5)

    def test_mmorpg_physics_engine(self):
        """Test MMORPG physics compute integration."""
        engine = GameComputeEngine()
        pos = np.array([[0.0, 0.0, 50.0], [10.0, 20.0, 0.0]], dtype=np.float32)
        vel = np.array([[0.0, 0.0, -10.0], [5.0, -5.0, 0.0]], dtype=np.float32)
        acc = np.array([[0.0, 0.0, -9.81], [0.0, 0.0, 0.0]], dtype=np.float32)

        new_pos, new_vel = engine.simulate_entity_physics(pos, vel, acc, dt=0.1)
        self.assertEqual(new_pos.shape, (2, 3))
        self.assertEqual(new_vel.shape, (2, 3))
        # Z position should decrease due to gravity
        self.assertLess(new_pos[0, 2], 50.0)

    def test_image_filter_pipeline(self):
        """Test ImageFilterPipeline filters on synthetic image."""
        pipeline = ImageFilterPipeline()
        img = np.zeros((16, 16, 3), dtype=np.uint8)
        img[4:12, 4:12] = 200

        # Contrast
        contrast_img = pipeline.adjust_brightness_contrast(img, brightness=10.0, contrast=1.2)
        self.assertEqual(contrast_img.shape, img.shape)

        # Sobel
        edges = pipeline.sobel_edges(img)
        self.assertEqual(edges.shape, (16, 16))
        self.assertGreater(np.max(edges), 0)


if __name__ == "__main__":
    unittest.main()
