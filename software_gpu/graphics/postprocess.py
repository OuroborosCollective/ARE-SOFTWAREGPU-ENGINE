"""
Modern Gaming PC Post-Processing & Anti-Aliasing (AA) Subsystem.
Implements 4x MSAA, FXAA (Fast Approximate Anti-Aliasing),
HDR Bloom / Glow, and ACES Filmic Tone Mapping with Gamma 2.2 Correction.
"""

from typing import Tuple, List, Optional
import numpy as np

from .framebuffer import Framebuffer
from .shader import Shader, Vertex
from .rasterizer import edge_function


class MSAAFramebuffer:
    """Multi-Sample Framebuffer supporting 4x MSAA sub-pixel coverage sampling."""
    def __init__(self, width: int, height: int, samples: int = 4):
        if samples != 4:
            raise ValueError("Only 4x MSAA sample positions are supported")
        self.width = width
        self.height = height
        self.samples = samples
        # Standard rotated grid / box sub-sample offsets in [-0.5, 0.5]
        self.sample_offsets = np.array([
            [-0.25, -0.25],
            [ 0.25, -0.25],
            [-0.25,  0.25],
            [ 0.25,  0.25],
        ], dtype=np.float32)

        # 4D Multi-sample color buffer: [H, W, SAMPLES, 4] (RGBA)
        self.color_samples = np.zeros((height, width, samples, 4), dtype=np.uint8)
        # 3D Multi-sample depth buffer: [H, W, SAMPLES]
        self.depth_samples = np.full((height, width, samples), 1.0, dtype=np.float32)

    def clear(self, r: int = 20, g: int = 25, b: int = 35, a: int = 255, depth: float = 1.0) -> None:
        self.color_samples[..., 0] = r
        self.color_samples[..., 1] = g
        self.color_samples[..., 2] = b
        self.color_samples[..., 3] = a
        self.depth_samples.fill(depth)

    def resolve(self) -> Framebuffer:
        """Resolves multi-sample buffer into single anti-aliased framebuffer via box filter."""
        resolved_fb = Framebuffer(self.width, self.height)
        # Average sub-pixel color samples
        # Four uint8 samples sum to at most 1020. This matches the previous
        # float average + uint8 truncation without allocating a float32 copy.
        avg_color = np.sum(self.color_samples, axis=2, dtype=np.uint16)
        resolved_fb.color_buffer[...] = (avg_color // 4).astype(np.uint8)
        # Depth minimum resolve
        resolved_fb.depth_buffer[...] = np.min(self.depth_samples, axis=2)
        return resolved_fb


class FXAAPass:
    """Fast Approximate Anti-Aliasing (FXAA) Post-Processing Pass.
    Detects high-contrast edge gradients and applies sub-pixel blending along edge tangents.
    """
    @staticmethod
    def apply(fb: Framebuffer, edge_threshold: float = 0.08, subpixel_quality: float = 0.75) -> Framebuffer:
        """Applies FXAA pass on input framebuffer and returns smoothed framebuffer."""
        img = fb.color_buffer[..., :3].astype(np.float32) / 255.0
        h, w = img.shape[:2]

        # Perceptual luminance calculation (Rec. 601)
        luma = 0.299 * img[..., 0] + 0.587 * img[..., 1] + 0.114 * img[..., 2]

        # Shifted luminance for 4-neighborhood
        luma_m = luma
        luma_n = np.pad(luma[:-1, :], ((1, 0), (0, 0)), mode='edge')
        luma_s = np.pad(luma[1:, :], ((0, 1), (0, 0)), mode='edge')
        luma_w = np.pad(luma[:, :-1], ((0, 0), (1, 0)), mode='edge')
        luma_e = np.pad(luma[:, 1:], ((0, 0), (0, 1)), mode='edge')

        range_min = np.minimum(luma_m, np.minimum(np.minimum(luma_n, luma_s), np.minimum(luma_w, luma_e)))
        range_max = np.maximum(luma_m, np.maximum(np.maximum(luma_n, luma_s), np.maximum(luma_w, luma_e)))
        range_contrast = range_max - range_min

        # Pixels with contrast below threshold require no anti-aliasing
        edge_mask = range_contrast >= edge_threshold

        # Sub-pixel edge filtering: low-pass 3x3 box average
        luma_corners = (
            np.pad(luma[:-1, :-1], ((1, 0), (1, 0)), mode='edge') +
            np.pad(luma[:-1, 1:], ((1, 0), (0, 1)), mode='edge') +
            np.pad(luma[1:, :-1], ((0, 1), (1, 0)), mode='edge') +
            np.pad(luma[1:, 1:], ((0, 1), (0, 1)), mode='edge')
        )
        luma_avg = (2.0 * (luma_n + luma_s + luma_w + luma_e) + luma_corners) / 12.0
        subpixel_offset = np.clip(np.abs(luma_avg - luma_m) / np.maximum(range_contrast, 1e-4), 0.0, 1.0)
        blend_factor = subpixel_offset * subpixel_quality

        # Determine edge direction (horizontal vs vertical gradient)
        edge_horiz = np.abs(luma_n + luma_s - 2.0 * luma_m)
        edge_vert = np.abs(luma_w + luma_e - 2.0 * luma_m)
        is_horizontal = edge_horiz >= edge_vert

        # Sample colors along perpendicular gradient
        out_img = img.copy()

        # Blend masked pixels
        img_n = np.pad(img[:-1, :, :], ((1, 0), (0, 0), (0, 0)), mode='edge')
        img_s = np.pad(img[1:, :, :], ((0, 1), (0, 0), (0, 0)), mode='edge')
        img_w = np.pad(img[:, :-1, :], ((0, 0), (1, 0), (0, 0)), mode='edge')
        img_e = np.pad(img[:, 1:, :], ((0, 0), (0, 1), (0, 0)), mode='edge')

        neighbor_avg = np.where(
            is_horizontal[..., None],
            0.5 * (img_n + img_s),
            0.5 * (img_w + img_e)
        )

        b_factor = blend_factor[..., None]
        blended = (1.0 - b_factor) * img + b_factor * neighbor_avg

        out_img = np.where(edge_mask[..., None], blended, img)

        out_fb = Framebuffer(w, h)
        out_fb.color_buffer[..., :3] = np.clip(out_img * 255.0, 0.0, 255.0).astype(np.uint8)
        out_fb.color_buffer[..., 3] = fb.color_buffer[..., 3]
        out_fb.depth_buffer[...] = fb.depth_buffer[...]
        return out_fb


class GamingPostProcessing:
    """Full Modern Gaming PC Post-Processing Pipeline:
    HDR ACES Filmic Tone Mapping, Bloom / Glow, and Gamma 2.2 Correction.
    """
    @staticmethod
    def aces_tone_mapping(color_linear: np.ndarray) -> np.ndarray:
        """ACES Filmic tone mapping curve for cinematic dynamic range."""
        a = 2.51
        b = 0.03
        c = 2.43
        d = 0.59
        e = 0.14
        x = np.maximum(0.0, color_linear)
        return np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0)

    @staticmethod
    def gamma_correction(color_linear: np.ndarray, gamma: float = 2.2) -> np.ndarray:
        """Applies sRGB gamma curve: C_srgb = C_linear^(1/gamma)."""
        return np.power(np.maximum(0.0, color_linear), 1.0 / gamma)

    @classmethod
    def apply_bloom_and_hdr(
        cls,
        fb: Framebuffer,
        bloom_threshold: float = 0.7,
        bloom_intensity: float = 0.4,
        exposure: float = 1.2
    ) -> Framebuffer:
        """Applies HDR extraction, 2-pass Bloom glow, and ACES tone mapping."""
        h, w = fb.height, fb.width
        raw_rgb = fb.color_buffer[..., :3].astype(np.float32) / 255.0

        # Exposure scaling
        hdr_color = raw_rgb * exposure

        # 1. High-Pass Brightness Threshold for Bloom
        luma = 0.299 * hdr_color[..., 0] + 0.587 * hdr_color[..., 1] + 0.114 * hdr_color[..., 2]
        bright_mask = np.maximum(0.0, luma - bloom_threshold) / (1.0 - bloom_threshold + 1e-4)
        bloom_source = hdr_color * bright_mask[..., None]

        # 2. Fast Separable 2D Box Blur for Glow
        k = 5
        kernel_1d = np.ones(k, dtype=np.float32) / float(k)

        # Horizontal blur
        pad_x = k // 2
        padded_x = np.pad(bloom_source, ((0, 0), (pad_x, pad_x), (0, 0)), mode='edge')
        blurred_h = np.zeros_like(bloom_source)
        for i in range(k):
            blurred_h += padded_x[:, i:i+w, :] * kernel_1d[i]

        # Vertical blur
        pad_y = k // 2
        padded_y = np.pad(blurred_h, ((pad_y, pad_y), (0, 0), (0, 0)), mode='edge')
        blurred_bloom = np.zeros_like(bloom_source)
        for i in range(k):
            blurred_bloom += padded_y[i:i+h, :, :] * kernel_1d[i]

        # 3. Additive Blend
        composite_hdr = hdr_color + blurred_bloom * bloom_intensity

        # 4. ACES Tone Mapping + Gamma 2.2
        tone_mapped = cls.aces_tone_mapping(composite_hdr)
        gamma_corrected = cls.gamma_correction(tone_mapped, gamma=2.2)

        out_fb = Framebuffer(w, h)
        out_fb.color_buffer[..., :3] = np.clip(gamma_corrected * 255.0, 0.0, 255.0).astype(np.uint8)
        out_fb.color_buffer[..., 3] = 255
        out_fb.depth_buffer[...] = fb.depth_buffer[...]
        return out_fb


class MSAARasterizer:
    """Rasterizer with 4x MSAA sub-pixel coverage testing for edge smoothing."""
    def __init__(self, msaa_fb: MSAAFramebuffer):
        self.msaa_fb = msaa_fb

    def draw_mesh(self, vertices: List[Vertex], indices: List[Tuple[int, int, int]], shader: Shader) -> None:
        """Draws mesh with 4x sub-pixel coverage evaluation."""
        w = float(self.msaa_fb.width)
        h = float(self.msaa_fb.height)

        # Vertex Shader pass
        transformed = []
        varyings = []
        for v in vertices:
            clip, var = shader.vertex_shader(v)
            transformed.append(clip)
            varyings.append(var)

        for i0, i1, i2 in indices:
            p0, p1, p2 = transformed[i0], transformed[i1], transformed[i2]
            if p0[3] <= 0.01 or p1[3] <= 0.01 or p2[3] <= 0.01:
                continue

            inv_w0, inv_w1, inv_w2 = 1.0 / p0[3], 1.0 / p1[3], 1.0 / p2[3]
            ndc0 = p0[:3] * inv_w0
            ndc1 = p1[:3] * inv_w1
            ndc2 = p2[:3] * inv_w2

            s0 = np.array([(ndc0[0] + 1.0) * 0.5 * w, (1.0 - ndc0[1]) * 0.5 * h, ndc0[2]], dtype=np.float32)
            s1 = np.array([(ndc1[0] + 1.0) * 0.5 * w, (1.0 - ndc1[1]) * 0.5 * h, ndc1[2]], dtype=np.float32)
            s2 = np.array([(ndc2[0] + 1.0) * 0.5 * w, (1.0 - ndc2[1]) * 0.5 * h, ndc2[2]], dtype=np.float32)

            area = edge_function(s0, s1, s2)
            if area <= 0:
                continue
            inv_area = 1.0 / area

            min_x = max(0, int(np.floor(min(s0[0], s1[0], s2[0]))))
            max_x = min(self.msaa_fb.width - 1, int(np.ceil(max(s0[0], s1[0], s2[0]))))
            min_y = max(0, int(np.floor(min(s0[1], s1[1], s2[1]))))
            max_y = min(self.msaa_fb.height - 1, int(np.ceil(max(s0[1], s1[1], s2[1]))))

            if min_x > max_x or min_y > max_y:
                continue

            for py in range(min_y, max_y + 1):
                for px in range(min_x, max_x + 1):
                    # Test each of the 4 sub-pixel sample points!
                    sub_covered = []
                    sub_depths = []

                    for s_idx, (ox, oy) in enumerate(self.msaa_fb.sample_offsets):
                        sample_pt = np.array([px + 0.5 + ox, py + 0.5 + oy], dtype=np.float32)
                        w0 = edge_function(s1, s2, sample_pt)
                        w1 = edge_function(s2, s0, sample_pt)
                        w2 = edge_function(s0, s1, sample_pt)

                        if w0 >= 0 and w1 >= 0 and w2 >= 0:
                            a = w0 * inv_area
                            b = w1 * inv_area
                            c = w2 * inv_area
                            z = a * s0[2] + b * s1[2] + c * s2[2]
                            if z < self.msaa_fb.depth_samples[py, px, s_idx]:
                                sub_covered.append(s_idx)
                                sub_depths.append(z)

                    if not sub_covered:
                        continue

                    # Evaluate fragment shader once per pixel (standard MSAA optimization)
                    center_pt = np.array([px + 0.5, py + 0.5], dtype=np.float32)
                    cw0 = max(0.0, edge_function(s1, s2, center_pt)) * inv_area
                    cw1 = max(0.0, edge_function(s2, s0, center_pt)) * inv_area
                    cw2 = max(0.0, edge_function(s0, s1, center_pt)) * inv_area
                    c_sum = cw0 + cw1 + cw2
                    if c_sum > 1e-6:
                        cw0 /= c_sum
                        cw1 /= c_sum
                        cw2 /= c_sum

                    interp_inv_w = cw0 * inv_w0 + cw1 * inv_w1 + cw2 * inv_w2
                    interp_factor = 1.0 / interp_inv_w if interp_inv_w > 1e-9 else 1.0

                    interp_varyings = {}
                    for k in varyings[i0]:
                        val0, val1, val2 = varyings[i0][k], varyings[i1][k], varyings[i2][k]
                        if isinstance(val0, np.ndarray):
                            interp_varyings[k] = (cw0 * (val0 * inv_w0) + cw1 * (val1 * inv_w1) + cw2 * (val2 * inv_w2)) * interp_factor
                        else:
                            interp_varyings[k] = val0

                    r, g, b, a = shader.fragment_shader(interp_varyings)

                    # Store color and update depth only for covered sub-samples!
                    for s_idx, z in zip(sub_covered, sub_depths):
                        self.msaa_fb.depth_samples[py, px, s_idx] = z
                        self.msaa_fb.color_samples[py, px, s_idx, 0] = r
                        self.msaa_fb.color_samples[py, px, s_idx, 1] = g
                        self.msaa_fb.color_samples[py, px, s_idx, 2] = b
                        self.msaa_fb.color_samples[py, px, s_idx, 3] = a
