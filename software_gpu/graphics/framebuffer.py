"""RGBA8 framebuffer, Float32 depth, exact BMP/PPM exports.

Independent local export candidates are calibrated only when explicitly enabled
by an existing ARE learning database. Rendering/depth are not modified.
"""
import struct
from typing import Tuple, Optional
import numpy as np

from ..learning_routes import measured_bytes


class Framebuffer:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.color_buffer = np.zeros((height, width, 4), dtype=np.uint8)
        self.depth_buffer = np.full((height, width), 1.0, dtype=np.float32)
        self.last_export_learning_receipt = None

    def clear(self, r: int = 20, g: int = 25, b: int = 35, a: int = 255,
              depth: float = 1.0) -> None:
        import sys
        if sys.byteorder == 'little':
            color_val = int(r) | (int(g) << 8) | (int(b) << 16) | (int(a) << 24)
        else:
            color_val = (int(r) << 24) | (int(g) << 16) | (int(b) << 8) | int(a)
        self.color_buffer.view(np.uint32).fill(color_val)
        self.depth_buffer.fill(depth)

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int,
                  a: int = 255, z: float = 0.0) -> bool:
        if 0 <= x < self.width and 0 <= y < self.height:
            if z < self.depth_buffer[y, x]:
                self.depth_buffer[y, x] = z
                self.color_buffer[y, x, 0] = r
                self.color_buffer[y, x, 1] = g
                self.color_buffer[y, x, 2] = b
                self.color_buffer[y, x, 3] = a
                return True
        return False

    def to_ppm_bytes(self) -> bytes:
        """PPM P6 with exactly original RGB ordering and zero file effects."""
        header = f"P6\n{self.width} {self.height}\n255\n".encode('ascii')
        rgb = self.color_buffer[..., :3]
        def reference():
            return header + rgb.tobytes()
        def candidate():
            # A distinct, contiguous NumPy packing path; no channel changes.
            return header + np.ascontiguousarray(rgb).tobytes(order='C')
        result, receipt = measured_bytes('ppm-byte-export', self.width,
                                        self.height, rgb.size, reference, candidate, __file__)
        self.last_export_learning_receipt = receipt
        return result

    def save_ppm(self, file_path: str) -> None:
        with open(file_path, 'wb') as out:
            out.write(self.to_ppm_bytes())

    def to_bmp_bytes(self) -> bytes:
        """BMP BGR24 with exact header, row padding and bottom-up order."""
        w, h = self.width, self.height
        row_stride = (w * 3 + 3) & ~3
        img_size = row_stride * h
        file_size = 54 + img_size
        bmp_header = struct.pack('<2sIHHI', b'BM', file_size, 0, 0, 54)
        dib_header = struct.pack('<IIIHHIIIIII', 40, w, h, 1, 24, 0,
                                 img_size, 2835, 2835, 0, 0)
        prefix = bmp_header + dib_header
        rgb = self.color_buffer
        padding = row_stride - (w * 3)

        def reference():
            bgr = rgb[::-1, :, :3][..., [2, 1, 0]]
            if padding > 0:
                zero = bytes(padding)
                pixel_data = b''.join(row.tobytes() + zero for row in bgr)
            else:
                pixel_data = bgr.tobytes()
            return prefix + pixel_data

        def candidate():
            # Alternate row-independent byte packing, keeping exact BMP bytes.
            channels = (rgb[::-1, :, 2], rgb[::-1, :, 1], rgb[::-1, :, 0])
            bgr = np.stack(channels, axis=2)
            if padding:
                # Preallocated contiguous output avoids per-row Python joins.
                pixels = np.zeros((h, row_stride), dtype=np.uint8)
                pixels[:, :w * 3] = bgr.reshape(h, w * 3)
                return prefix + pixels.tobytes()
            return prefix + bgr.tobytes()

        result, receipt = measured_bytes('bmp-byte-export', w, h,
                                        rgb.nbytes, reference, candidate, __file__)
        self.last_export_learning_receipt = receipt
        return result

    def save_bmp(self, file_path: str) -> None:
        with open(file_path, 'wb') as out:
            out.write(self.to_bmp_bytes())
