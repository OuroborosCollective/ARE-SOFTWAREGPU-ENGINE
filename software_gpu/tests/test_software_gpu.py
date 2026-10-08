"""
Unit and Integration Tests for SoftwareGPU.
NO MOCKS, NO STUBS - executes real mathematical algorithms and rendering pipelines.
Verifies numerical precision against CPU analytical references.
"""

import unittest
import numpy as np
import os
import tempfile

from software_gpu.core.device import VirtualGPU
from software_gpu.core.memory import GPUMemoryManager
from software_gpu.core.types import Dim3, GPUArray
from software_gpu.compute.executor import SIMTExecutor, KernelLaunchConfig
from software_gpu.compute.compiler import cuda_kernel
from software_gpu.compute.kernels import (
    matmul_tiled_simt_kernel,
    parallel_reduction_sum_kernel,
    conv2d_simt_kernel,
    VectorizedGPUKernels
)
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Vertex, BlinnPhongShader, Matrix4
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.redirector.cuda_runtime import cuda
from software_gpu.redirector.interceptor import GPURedirector


class TestSoftwareGPU(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = VirtualGPU.get_current_device()

    def setUp(self):
        self.device.reset()

    def test_memory_allocation_and_transfers(self):
        """Test real virtual VRAM allocation and Host-to-Device / Device-to-Host transfers."""
        host_data = np.array([1.5, 2.5, 3.5, 4.5], dtype=np.float32)
        dev_arr = self.device.memory.to_device(host_data)
        
        self.assertIsInstance(dev_arr, GPUArray)
        self.assertEqual(dev_arr.shape, (4,))
        self.assertEqual(dev_arr.dtype, np.float32)
        self.assertGreater(dev_arr.device_ptr, 0)
        
        # Verify content copied to host matches exactly
        copied_back = dev_arr.to_numpy()
        np.testing.assert_array_equal(copied_back, host_data)

    def test_simt_vector_add_kernel(self):
        """Test real SIMT kernel launch across grid and blocks for vector addition."""
        @cuda_kernel
        def vec_add(ctx, a, b, c, n):
            idx = ctx.blockIdx.x * ctx.blockDim.x + ctx.threadIdx.x
            if idx < n:
                c[idx] = a[idx] + b[idx]

        N = 1024
        a_np = np.linspace(1.0, 100.0, N, dtype=np.float32)
        b_np = np.linspace(200.0, 300.0, N, dtype=np.float32)

        d_a = self.device.memory.to_device(a_np)
        d_b = self.device.memory.to_device(b_np)
        d_c = self.device.memory.allocate((N,), dtype=np.float32)

        block_dim = 64
        grid_dim = (N + block_dim - 1) // block_dim

        vec_add[grid_dim, block_dim](d_a, d_b, d_c, N)

        res = d_c.to_numpy()
        expected = a_np + b_np
        np.testing.assert_allclose(res, expected, rtol=1e-5, atol=1e-5)

    def test_simt_tiled_matmul_with_shared_memory_and_barriers(self):
        """Test real CUDA-style Tiled GEMM using cooperative shared memory and barrier synchronization."""
        compiled_kernel = cuda_kernel(matmul_tiled_simt_kernel)

        N = 32
        TILE_SIZE = 8
        np.random.seed(42)
        A_np = np.random.randn(N, N).astype(np.float32)
        B_np = np.random.randn(N, N).astype(np.float32)

        d_a = self.device.memory.to_device(A_np)
        d_b = self.device.memory.to_device(B_np)
        d_c = self.device.memory.allocate((N, N), dtype=np.float32)

        grid_dim = ((N + TILE_SIZE - 1) // TILE_SIZE, (N + TILE_SIZE - 1) // TILE_SIZE)
        block_dim = (TILE_SIZE, TILE_SIZE)
        shared_size = 2 * TILE_SIZE * TILE_SIZE

        compiled_kernel[grid_dim, block_dim, shared_size](d_a, d_b, d_c, N, TILE_SIZE)

        result = d_c.to_numpy()
        expected = np.matmul(A_np, B_np)
        np.testing.assert_allclose(result, expected, rtol=1e-4, atol=1e-4)

    def test_simt_parallel_reduction_tree(self):
        """Test real CUDA-style Tree Reduction with shared memory and barriers."""
        compiled_kernel = cuda_kernel(parallel_reduction_sum_kernel)

        # 8 blocks of 16 threads each = 128 elements per block
        threads_per_block = 16
        elements_per_block = threads_per_block * 2
        num_blocks = 4
        N = num_blocks * elements_per_block

        data = np.arange(1, N + 1, dtype=np.float32)
        d_in = self.device.memory.to_device(data)
        d_out = self.device.memory.allocate((num_blocks,), dtype=np.float32)

        shared_size = threads_per_block
        compiled_kernel[num_blocks, threads_per_block, shared_size](d_in, d_out, N)

        block_sums = d_out.to_numpy()
        total_sum = np.sum(block_sums)
        expected_sum = np.sum(data)

        self.assertAlmostEqual(float(total_sum), float(expected_sum), delta=1e-2)

    def test_simt_conv2d_image_filter(self):
        """Test real 2D Image Convolution kernel on 2D grid."""
        compiled_kernel = cuda_kernel(conv2d_simt_kernel)

        W, H = 16, 16
        image_np = np.zeros((H, W), dtype=np.float32)
        image_np[4:12, 4:12] = 10.0  # Bright square

        # 3x3 Box Blur kernel
        kernel_np = np.ones((3, 3), dtype=np.float32) / 9.0

        d_img = self.device.memory.to_device(image_np)
        d_krn = self.device.memory.to_device(kernel_np)
        d_out = self.device.memory.allocate((H, W), dtype=np.float32)

        block_dim = (4, 4)
        grid_dim = ((W + 3) // 4, (H + 3) // 4)

        compiled_kernel[grid_dim, block_dim](d_img, d_krn, d_out, W, H, 3)

        output = d_out.to_numpy()
        # Interior of the square should be exactly 10.0
        self.assertAlmostEqual(output[6, 6], 10.0, places=4)
        # Background outside square apron should be 0.0
        self.assertAlmostEqual(output[0, 0], 0.0, places=4)
        # Edge boundary should be blurred between 0 and 10
        self.assertTrue(0.0 < output[4, 4] < 10.0)

    def test_vectorized_high_throughput_kernels(self):
        """Test SIMD-accelerated GEMM and activation functions."""
        N = 64
        A = np.random.randn(N, N).astype(np.float32)
        B = np.random.randn(N, N).astype(np.float32)
        d_a = self.device.memory.to_device(A)
        d_b = self.device.memory.to_device(B)
        d_c = self.device.memory.allocate((N, N), dtype=np.float32)

        VectorizedGPUKernels.gemm_parallel(d_a, d_b, d_c)
        np.testing.assert_allclose(d_c.to_numpy(), A @ B, rtol=1e-5, atol=1e-5)

        # ReLU test
        X = np.array([-5.0, 0.0, 3.2, -1.1, 7.8], dtype=np.float32)
        d_x = self.device.memory.to_device(X)
        d_out = self.device.memory.allocate(X.shape, dtype=np.float32)
        VectorizedGPUKernels.relu(d_x, d_out)
        np.testing.assert_array_equal(d_out.to_numpy(), np.maximum(X, 0.0))

    def test_graphics_software_rasterization_pipeline(self):
        """Test full 3D Graphics rasterization pipeline with early-Z buffering and shading."""
        width, height = 128, 128
        fb = Framebuffer(width, height)
        fb.clear(r=10, g=10, b=10, a=255, depth=1.0)

        # Create two overlapping triangles in 3D: Front triangle (red, Z=0.8, closer to eye at Z=2.0)
        # and Back triangle (blue, Z=0.2, further from eye at Z=2.0)
        # Verify that Early-Z test occludes the back triangle!
        front_verts = [
            Vertex(position=np.array([-0.5, -0.5, 0.8]), color=np.array([1.0, 0.0, 0.0])),
            Vertex(position=np.array([0.5, -0.5, 0.8]), color=np.array([1.0, 0.0, 0.0])),
            Vertex(position=np.array([0.0, 0.5, 0.8]), color=np.array([1.0, 0.0, 0.0])),
        ]
        front_indices = [(0, 1, 2)]

        back_verts = [
            Vertex(position=np.array([-0.6, -0.6, 0.2]), color=np.array([0.0, 0.0, 1.0])),
            Vertex(position=np.array([0.6, -0.6, 0.2]), color=np.array([0.0, 0.0, 1.0])),
            Vertex(position=np.array([0.0, 0.6, 0.2]), color=np.array([0.0, 0.0, 1.0])),
        ]
        back_indices = [(0, 1, 2)]

        model = Matrix4.identity()
        view = Matrix4.look_at(
            eye=np.array([0.0, 0.0, 2.0]),
            target=np.array([0.0, 0.0, 0.0]),
            up=np.array([0.0, 1.0, 0.0])
        )
        proj = Matrix4.perspective(fov_rad=np.radians(60.0), aspect=1.0, near=0.1, far=10.0)

        shader_front = BlinnPhongShader(model, view, proj, diffuse_color=np.array([1.0, 0.0, 0.0]))
        shader_back = BlinnPhongShader(model, view, proj, diffuse_color=np.array([0.0, 0.0, 1.0]))

        rasterizer = SoftwareRasterizer(fb)
        # Render back first, then front; or front first then back: Z-buffer ensures front wins!
        rasterizer.draw_mesh(front_verts, front_indices, shader_front)
        rasterizer.draw_mesh(back_verts, back_indices, shader_back)

        # Center pixel (64, 64) should be dominated by the FRONT red triangle because of Z-buffering!
        center_color = fb.color_buffer[64, 64]
        self.assertGreater(center_color[0], center_color[2], "Front red triangle must occlude back blue triangle!")

        # Verify BMP export works without errors
        with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as f:
            tmp_path = f.name
        try:
            fb.save_bmp(tmp_path)
            self.assertTrue(os.path.exists(tmp_path))
            self.assertGreater(os.path.getsize(tmp_path), 54)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_cuda_dropin_runtime(self):
        """Test drop-in CUDA runtime interface."""
        self.assertTrue(cuda.is_available())
        self.assertEqual(cuda.device_count(), 1)
        self.assertIn("Software-GPU", cuda.get_device_name())

        arr = np.array([10, 20, 30], dtype=np.float32)
        d_arr = cuda.to_device(arr)
        np.testing.assert_array_equal(d_arr.to_numpy(), arr)

    def test_task_redirection(self):
        """Test GPU task interceptor and redirection engine."""
        redirector = GPURedirector()
        A = np.random.randn(32, 32).astype(np.float32)
        B = np.random.randn(32, 32).astype(np.float32)

        res, stats = redirector.execute_gemm(A, B, target_device="cuda")
        self.assertEqual(stats["redirected_from"], "cuda")
        self.assertIn("SoftwareGPU", stats["redirected_to"])
        np.testing.assert_allclose(res, A @ B, rtol=1e-5, atol=1e-5)


if __name__ == "__main__":
    unittest.main()
