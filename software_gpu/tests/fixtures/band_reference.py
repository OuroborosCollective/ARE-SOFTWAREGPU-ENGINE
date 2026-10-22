"""Frozen band oracle from main 048d794ba563f64af317cd216061d3a85d9cbafa.
Do not optimize: independent pre-inline arithmetic and allocation order.
"""
import numpy as np
from software_gpu.graphics.geometry import edge_function, edge_covered
from software_gpu.graphics.shader import Shader

def _rasterize_band(self, triangles: list, shader: Shader, y_start: int, y_end: int) -> None:
    """Rasterizes triangles that overlap the vertical band [y_start, y_end)."""
    fb_w = self.fb.width
    for (s0, s1, s2, inv_w0, inv_w1, inv_w2, v0_var, v1_var, v2_var, area) in triangles:
        # Triangle 2D bounding box
        min_x = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
        max_x = min(fb_w - 1, int(np.ceil(max(s0[0], s1[0], s2[0]))))
        min_y = max(y_start, int(np.floor(min(s0[1], s1[1], s2[1]))))
        max_y = min(y_end - 1, int(np.ceil(max(s0[1], s1[1], s2[1]))))

        if min_x > max_x or min_y > max_y:
            continue

        inv_area = 1.0 / area

        for py in range(min_y, max_y + 1):
            p_y = py + 0.5
            for px in range(min_x, max_x + 1):
                p_x = px + 0.5
                p = np.array([p_x, p_y], dtype=np.float32)

                # Barycentric coordinates via edge functions
                w0 = edge_function(s1, s2, p)
                w1 = edge_function(s2, s0, p)
                w2 = edge_function(s0, s1, p)

                # Inside triangle test
                if (edge_covered(w0, s1, s2) and edge_covered(w1, s2, s0) and
                        edge_covered(w2, s0, s1)):
                    alpha = w0 * inv_area
                    beta = w1 * inv_area
                    gamma = w2 * inv_area

                    # Interpolate depth Z (screen space)
                    z_val = alpha * s0[2] + beta * s1[2] + gamma * s2[2]

                    # Early-Z depth test
                    if z_val < self.fb.depth_buffer[py, px]:
                        # Perspective-correct interpolation factor
                        interp_inv_w = alpha * inv_w0 + beta * inv_w1 + gamma * inv_w2
                        interp_factor = 1.0 / interp_inv_w if interp_inv_w > 1e-9 else 1.0

                        # Interpolate varying attributes
                        interpolated_varyings = {}
                        for k in v0_var:
                            val0, val1, val2 = v0_var[k], v1_var[k], v2_var[k]
                            if isinstance(val0, np.ndarray):
                                weighted = (
                                    alpha * (val0 * inv_w0) +
                                    beta * (val1 * inv_w1) +
                                    gamma * (val2 * inv_w2)
                                ) * interp_factor
                                interpolated_varyings[k] = weighted
                            else:
                                interpolated_varyings[k] = val0

                        # Fragment Shader Invocation
                        r, g, b, a = shader.fragment_shader(interpolated_varyings)

                        # Update Framebuffer and Depth buffer
                        self.fb.depth_buffer[py, px] = z_val
                        self.fb.color_buffer[py, px, 0] = r
                        self.fb.color_buffer[py, px, 1] = g
                        self.fb.color_buffer[py, px, 2] = b
                        self.fb.color_buffer[py, px, 3] = a
