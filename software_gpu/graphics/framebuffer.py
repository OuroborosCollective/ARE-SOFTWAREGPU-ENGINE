"""
Framebuffer and Image Output Subsystem for SoftwareGPU.
Supports 32-bit RGBA color buffers, 32-bit float Z-buffers,
and zero-dependency export to standard image formats (BMP / PPM).
"""

import struct
from typing import Tuple, Optional
import numpy as np


class Framebuffer:
    """Represents the GPU display framebuffer (Color + Depth/Stencil buffers)."""
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        # RGBA 8-bit per channel
        self.color_buffer = np.zeros((height, width, 4), dtype=np.uint8)
        # 32-bit floating point depth buffer (Z-buffer, initialized to +inf or 1.0)
        self.depth_buffer = np.full((height, width), 1.0, dtype=np.float32)

    def clear(self, r: int = 20, g: int = 25, b: int = 35, a: int = 255, depth: float = 1.0) -> None:
        """Clears color and depth buffers (glClear equivalent)."""
        self.color_buffer[..., 0] = r
        self.color_buffer[..., 1] = g
        self.color_buffer[..., 2] = b
        self.color_buffer[..., 3] = a
        self.depth_buffer.fill(depth)

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int, a: int = 255, z: float = 0.0) -> bool:
        """Sets a pixel if passing depth test."""
        if 0 <= x < self.width and 0 <= y < self.height:
            if z < self.depth_buffer[y, x]:
                self.depth_buffer[y, x] = z
                self.color_buffer[y, x, 0] = r
                self.color_buffer[y, x, 1] = g
                self.color_buffer[y, x, 2] = b
                self.color_buffer[y, x, 3] = a
                return True
        return False

    def save_ppm(self, file_path: str) -> None:
        """Exports the framebuffer as a standard ASCII/Binary PPM image file."""
        rgb = self.color_buffer[..., :3]
        header = f"P6\n{self.width} {self.height}\n255\n".encode("ascii")
        with open(file_path, "wb") as f:
            f.write(header)
            f.write(rgb.tobytes())

    def save_bmp(self, file_path: str) -> None:
        """Exports the framebuffer as an uncompressed 24-bit BMP image file."""
        w, h = self.width, self.height
        row_stride = (w * 3 + 3) & ~3
        img_size = row_stride * h
        file_size = 54 + img_size

        # BMP Header (14 bytes) + DIB Header (40 bytes)
        bmp_header = struct.pack(
            "<2sIHHI",
            b"BM",
            file_size,
            0,
            0,
            54
        )
        dib_header = struct.pack(
            "<IIIHHIIIIII",
            40,
            w,
            h,  # bottom-to-top order
            1,  # planes
            24, # bpp
            0,  # uncompressed BI_RGB
            img_size,
            2835, # 72 DPI
            2835,
            0,
            0
        )

        # Convert RGB to BGR and flip vertically for standard BMP
        bgr = self.color_buffer[::-1, :, :3][..., [2, 1, 0]]
        
        # Add padding if row width is not aligned to 4 bytes
        padding = row_stride - (w * 3)
        if padding > 0:
            padded_rows = []
            pad_bytes = bytes(padding)
            for row in bgr:
                padded_rows.append(row.tobytes() + pad_bytes)
            pixel_data = b"".join(padded_rows)
        else:
            pixel_data = bgr.tobytes()

        with open(file_path, "wb") as f:
            f.write(bmp_header)
            f.write(dib_header)
            f.write(pixel_data)
