"""
Image Processing & Photo Editing GPU Compute Endpoint.
Offloads spatial filtering (Gaussian blur, Sobel edge detection, sharpen, color grading)
for graphics editors (GIMP, Photoshop, Krita, web editors) onto SoftwareGPU.
"""

from operator import index

import numpy as np
from typing import Tuple, Optional
import struct

from software_gpu.core.device import VirtualGPU
from software_gpu.core.types import GPUArray
from software_gpu.compute.compiler import cuda_kernel
from software_gpu.compute.kernels import conv2d_simt_kernel, VectorizedGPUKernels
from software_gpu.core.output import output_file


# Radius 63 keeps the float32 kernel below 64 KiB. The work budget
# accommodates the bundled 400 x 300 RGB demo at radius 3.
_MAX_GAUSSIAN_RADIUS = 63
_MAX_GAUSSIAN_WORK = 20_000_000


class ImageFilterPipeline:
    """Image processing pipeline utilizing SoftwareGPU acceleration."""
    def __init__(self):
        self.device = VirtualGPU.get_current_device()
        self._conv_kernel = cuda_kernel(conv2d_simt_kernel)

    def gaussian_blur(self, image: np.ndarray, radius: int = 2) -> np.ndarray:
        """Blur a nonempty grayscale or multichannel image on SoftwareGPU.

        Radius must be an integer from 0 through 63. Raises ValueError if
        the radius, image shape, or total convolution work exceeds the limits.
        """
        radius = index(radius)
        if not 0 <= radius <= _MAX_GAUSSIAN_RADIUS:
            raise ValueError(f"Gaussian blur radius must be between 0 and {_MAX_GAUSSIAN_RADIUS}")
        if image.ndim not in (2, 3) or 0 in image.shape:
            raise ValueError("Gaussian blur requires a nonempty 2D or 3D image")

        h, w = image.shape[:2]
        is_rgb = image.ndim == 3
        channel_count = image.shape[2] if is_rgb else 1
        block_dim = (8, 8)
        grid_dim = ((w + 7) // 8, (h + 7) // 8)

        ksize = 2 * radius + 1
        # Count both convolution taps and thread setup, including padded threads.
        threads = grid_dim[0] * grid_dim[1] * block_dim[0] * block_dim[1]
        if channel_count * (h * w * ksize**2 + threads) > _MAX_GAUSSIAN_WORK:
            raise ValueError("Gaussian blur exceeds the convolution work limit")

        # Generate 1D Gaussian kernel
        x = np.arange(-radius, radius + 1, dtype=np.float32)
        sigma = radius / 2.0 if radius > 0 else 1.0
        gauss_1d = np.exp(-0.5 * (x / sigma) ** 2)
        gauss_2d = np.outer(gauss_1d, gauss_1d)
        gauss_2d /= np.sum(gauss_2d)

        d_krn = self.device.memory.to_device(gauss_2d)

        if is_rgb:
            channels = []
            for c in range(channel_count):
                chan = image[..., c].astype(np.float32)
                d_in = self.device.memory.to_device(chan)
                d_out = self.device.memory.allocate((h, w), dtype=np.float32)
                self._conv_kernel[grid_dim, block_dim](d_in, d_krn, d_out, w, h, ksize)
                channels.append(d_out.to_numpy())
                self.device.memory.free(d_in)
                self.device.memory.free(d_out)
            result = np.stack(channels, axis=-1)
        else:
            d_in = self.device.memory.to_device(image.astype(np.float32))
            d_out = self.device.memory.allocate((h, w), dtype=np.float32)
            self._conv_kernel[grid_dim, block_dim](d_in, d_krn, d_out, w, h, ksize)
            result = d_out.to_numpy()
            self.device.memory.free(d_in)
            self.device.memory.free(d_out)

        self.device.memory.free(d_krn)
        return np.clip(result, 0.0, 255.0).astype(image.dtype)

    def sobel_edges(self, image: np.ndarray) -> np.ndarray:
        """Computes Sobel gradient magnitude edge detection."""
        h, w = image.shape[:2]
        gray = image.mean(axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)

        sobel_x = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
        sobel_y = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)

        d_img = self.device.memory.to_device(gray)
        d_kx = self.device.memory.to_device(sobel_x)
        d_ky = self.device.memory.to_device(sobel_y)
        d_gx = self.device.memory.allocate((h, w), dtype=np.float32)
        d_gy = self.device.memory.allocate((h, w), dtype=np.float32)

        block_dim = (8, 8)
        grid_dim = ((w + 7) // 8, (h + 7) // 8)

        self._conv_kernel[grid_dim, block_dim](d_img, d_kx, d_gx, w, h, 3)
        self._conv_kernel[grid_dim, block_dim](d_img, d_ky, d_gy, w, h, 3)

        gx = d_gx.to_numpy()
        gy = d_gy.to_numpy()
        mag = np.sqrt(gx ** 2 + gy ** 2)

        self.device.memory.free(d_img)
        self.device.memory.free(d_kx)
        self.device.memory.free(d_ky)
        self.device.memory.free(d_gx)
        self.device.memory.free(d_gy)

        return np.clip(mag, 0.0, 255.0).astype(np.uint8)

    def adjust_brightness_contrast(self, image: np.ndarray, brightness: float = 0.0, contrast: float = 1.0) -> np.ndarray:
        """SIMD vectorized brightness and contrast color grading."""
        d_in = self.device.memory.to_device(image.astype(np.float32))
        d_out = self.device.memory.allocate(image.shape, dtype=np.float32)

        # out = (in - 128) * contrast + 128 + brightness
        buf = d_in.raw_buffer
        res = (buf - 128.0) * contrast + 128.0 + brightness
        d_out.raw_buffer[...] = np.clip(res, 0.0, 255.0)

        result = d_out.to_numpy().astype(image.dtype)
        self.device.memory.free(d_in)
        self.device.memory.free(d_out)
        return result

    @staticmethod
    def load_bmp(file_path: str) -> np.ndarray:
        """Load a bottom-up, uncompressed 24-bit BMP as uint8 RGB [H, W, 3].

        Invalid or unsupported BMPs raise ValueError. Images are limited to
        16,384 rows and 16,777,216 pixels.
        """
        with open(file_path, "rb") as f:
            # The file header and common 40-byte DIB prefix cover all fields used.
            header = f.read(54)
            if len(header) != 54 or header[:2] != b"BM":
                raise ValueError("Invalid or truncated BMP header")
            offset, dib_size, w, h, planes, bpp, compression = struct.unpack_from(
                "<IIiiHHI", header, 10
            )
            if dib_size not in (40, 52, 56, 64, 108, 124):
                raise ValueError("Unsupported BMP DIB header")
            if planes != 1 or bpp != 24 or compression != 0:
                raise ValueError("BMP must use one plane and uncompressed 24-bit pixels")
            if w <= 0 or h <= 0:
                raise ValueError("BMP width and height must be positive")
            if h > _MAX_BMP_ROWS or w * h > _MAX_BMP_PIXELS:
                raise ValueError("BMP exceeds the row or pixel limit")
            if offset < 14 + dib_size:
                raise ValueError("BMP pixel offset overlaps the header")

            row_bytes_count = w * 3
            row_stride = (row_bytes_count + 3) & ~3
            pixel_size = row_stride * h
            if offset + pixel_size > f.seek(0, 2):
                raise ValueError("Truncated BMP pixel data")
            f.seek(offset)
            data = f.read(pixel_size)
            if len(data) != pixel_size:
                raise ValueError("Truncated BMP pixel data")

        pixels = np.zeros((h, w, 3), dtype=np.uint8)
        for y in range(h):
            row_start = (h - 1 - y) * row_stride
            row_bytes = data[row_start:row_start + row_bytes_count]
            row_arr = np.frombuffer(row_bytes, dtype=np.uint8).reshape((w, 3))
            # BGR to RGB
            pixels[y, :, 0] = row_arr[:, 2]
            pixels[y, :, 1] = row_arr[:, 1]
            pixels[y, :, 2] = row_arr[:, 0]
        return pixels

    @staticmethod
    def save_bmp(file_path: str, image: np.ndarray) -> None:
        """Saves RGB numpy array as 24-bit BMP."""
        h, w = image.shape[:2]
        from software_gpu.graphics.framebuffer import Framebuffer
        fb = Framebuffer(w, h)
        if len(image.shape) == 3:
            fb.color_buffer[..., :3] = image[..., :3]
        else:
            fb.color_buffer[..., 0] = image
            fb.color_buffer[..., 1] = image
            fb.color_buffer[..., 2] = image
        fb.color_buffer[..., 3] = 255
        fb.save_bmp(file_path)


if __name__ == "__main__":
    pipeline = ImageFilterPipeline()
    # Test on the rendered scene image
    src_img_path = output_file("software_gpu_sphere.bmp")
    img = pipeline.load_bmp(src_img_path)
    print(f"Loaded image from {src_img_path}, shape: {img.shape}")

    # 1. Apply Gaussian Blur
    blurred = pipeline.gaussian_blur(img, radius=3)
    out_blur = output_file("software_gpu_blurred.bmp")
    pipeline.save_bmp(out_blur, blurred)
    print(f"Gaussian Blur applied -> saved to {out_blur}")

    # 2. Apply Sobel Edge Detection
    edges = pipeline.sobel_edges(img)
    out_edges = output_file("software_gpu_sobel.bmp")
    pipeline.save_bmp(out_edges, edges)
    print(f"Sobel Edge Detection applied -> saved to {out_edges}")
