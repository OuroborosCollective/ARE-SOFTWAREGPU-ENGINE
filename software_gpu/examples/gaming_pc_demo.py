"""
Modern Gaming PC Visual Features Demo on SoftwareGPU.
Demonstrates 4x MSAA, FXAA (Fast Approximate Anti-Aliasing),
HDR Bloom / Glow, and ACES Filmic Tone Mapping with Gamma 2.2 Correction.
Saves comparison renders to demonstrate edge smoothing and high-dynamic-range lighting.
"""

import os
import time
import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Vertex, BlinnPhongShader, Matrix4
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.core.output import output_file
from software_gpu.graphics.postprocess import (
    MSAAFramebuffer,
    MSAARasterizer,
    FXAAPass,
    GamingPostProcessing
)


def create_high_contrast_scene() -> tuple:
    """Builds a high-contrast 3D mesh with sharp diagonal edges to highlight anti-aliasing."""
    # A prominent 3D sharp prism/wedge
    verts = [
        # Front triangle
        Vertex(np.array([-1.2, -0.8,  0.5]), np.array([0, 0, 1]), color=np.array([1.0, 0.2, 0.1])),
        Vertex(np.array([ 1.2, -0.8,  0.5]), np.array([0, 0, 1]), color=np.array([1.0, 0.2, 0.1])),
        Vertex(np.array([ 0.0,  1.2,  0.5]), np.array([0, 0, 1]), color=np.array([1.0, 0.2, 0.1])),
        # Overlapping bright neon bar across the diagonal
        Vertex(np.array([-1.5,  0.8,  0.7]), np.array([0, 0, 1]), color=np.array([0.2, 1.0, 0.9])),
        Vertex(np.array([ 1.5, -0.4,  0.7]), np.array([0, 0, 1]), color=np.array([0.2, 1.0, 0.9])),
        Vertex(np.array([ 1.3, -0.2,  0.7]), np.array([0, 0, 1]), color=np.array([0.2, 1.0, 0.9])),
    ]
    indices = [
        (0, 1, 2),
        (3, 4, 5)
    ]
    return verts, indices


def measure_edge_gradient_variance(fb: Framebuffer) -> float:
    """Measures edge gradient variance: lower values indicate smoother anti-aliased transitions."""
    gray = fb.color_buffer[..., :3].astype(np.float32).mean(axis=2)
    gx = np.diff(gray, axis=1)
    gy = np.diff(gray, axis=0)
    # Variance of gradients
    return float(np.var(gx) + np.var(gy))


def main():
    print("=" * 70)
    print(" Modern Gaming PC Pipeline on SoftwareGPU")
    print(" Features: 4x MSAA, FXAA, HDR Bloom, ACES Filmic Tone Mapping")
    print("=" * 70)

    W, H = 320, 240
    verts, indices = create_high_contrast_scene()

    model = Matrix4.rotation_z(np.radians(15.0))
    view = Matrix4.look_at(
        eye=np.array([0.0, 0.0, 3.0], dtype=np.float32),
        target=np.array([0.0, 0.0, 0.0], dtype=np.float32),
        up=np.array([0.0, 1.0, 0.0], dtype=np.float32)
    )
    proj = Matrix4.perspective(fov_rad=np.radians(50.0), aspect=W / H, near=0.1, far=10.0)

    # Vivid gaming shader with bright highlights
    shader = BlinnPhongShader(
        model, view, proj,
        diffuse_color=np.array([0.9, 0.3, 0.2], dtype=np.float32),
        specular_color=np.array([2.5, 2.5, 2.5], dtype=np.float32), # HDR specular
        shininess=64.0
    )

    # -------------------------------------------------------------
    # 1. Base Render (No AA - Aliased Jagged Edges)
    # -------------------------------------------------------------
    print("\n[1] Rendering Baseline (No Anti-Aliasing)...")
    fb_no_aa = Framebuffer(W, H)
    fb_no_aa.clear(15, 18, 25, 255, 1.0)
    rasterizer = SoftwareRasterizer(fb_no_aa)
    t0 = time.perf_counter()
    rasterizer.draw_mesh(verts, indices, shader)
    time_no_aa = (time.perf_counter() - t0) * 1000.0

    path_no_aa = output_file("gaming_aliased_no_aa.bmp")
    fb_no_aa.save_bmp(path_no_aa)
    var_no_aa = measure_edge_gradient_variance(fb_no_aa)
    print(f"  -> Saved to: {path_no_aa} ({time_no_aa:.1f} ms, Edge Variance: {var_no_aa:.1f})")

    # -------------------------------------------------------------
    # 2. 4x MSAA (Multi-Sample Anti-Aliasing with Sub-pixel Resolve)
    # -------------------------------------------------------------
    print("\n[2] Rendering with 4x MSAA (Sub-pixel Coverage & Box Resolve)...")
    msaa_fb = MSAAFramebuffer(W, H, samples=4)
    msaa_fb.clear(15, 18, 25, 255, 1.0)
    msaa_rast = MSAARasterizer(msaa_fb)
    t0 = time.perf_counter()
    msaa_rast.draw_mesh(verts, indices, shader)
    resolved_fb = msaa_fb.resolve()
    time_msaa = (time.perf_counter() - t0) * 1000.0

    path_msaa = output_file("gaming_msaa_4x.bmp")
    resolved_fb.save_bmp(path_msaa)
    var_msaa = measure_edge_gradient_variance(resolved_fb)
    print(f"  -> Saved to: {path_msaa} ({time_msaa:.1f} ms, Edge Variance: {var_msaa:.1f})")
    print(f"  -> Edge Smoothing Improvement: {(1.0 - var_msaa / var_no_aa) * 100:.1f}% smoother transitions!")

    # -------------------------------------------------------------
    # 3. FXAA (Fast Approximate Anti-Aliasing Post-Processing)
    # -------------------------------------------------------------
    print("\n[3] Applying FXAA (Luminance Gradient Edge Blending)...")
    t0 = time.perf_counter()
    fxaa_fb = FXAAPass.apply(fb_no_aa, edge_threshold=0.06, subpixel_quality=0.85)
    time_fxaa = (time.perf_counter() - t0) * 1000.0

    path_fxaa = output_file("gaming_fxaa.bmp")
    fxaa_fb.save_bmp(path_fxaa)
    var_fxaa = measure_edge_gradient_variance(fxaa_fb)
    print(f"  -> Saved to: {path_fxaa} ({time_fxaa:.1f} ms, Edge Variance: {var_fxaa:.1f})")
    print(f"  -> Edge Smoothing Improvement: {(1.0 - var_fxaa / var_no_aa) * 100:.1f}% smoother transitions!")

    # -------------------------------------------------------------
    # 4. HDR Bloom + ACES Filmic Tone Mapping + Gamma 2.2
    # -------------------------------------------------------------
    print("\n[4] Applying HDR Bloom Glow + ACES Filmic Tone Mapping...")
    t0 = time.perf_counter()
    hdr_fb = GamingPostProcessing.apply_bloom_and_hdr(
        resolved_fb,
        bloom_threshold=0.6,
        bloom_intensity=0.5,
        exposure=1.3
    )
    time_hdr = (time.perf_counter() - t0) * 1000.0

    path_hdr = output_file("gaming_hdr_bloom_aces.bmp")
    hdr_fb.save_bmp(path_hdr)
    print(f"  -> Saved to: {path_hdr} ({time_hdr:.1f} ms)")

    print("\n" + "=" * 70)
    print(" SUMMARY OF GAMING PC PIPELINE OUTPUTS:")
    print(f"  1. No AA (Aliased):  {path_no_aa} (Size: {os.path.getsize(path_no_aa):,} B)")
    print(f"  2. 4x MSAA:          {path_msaa} (Size: {os.path.getsize(path_msaa):,} B)")
    print(f"  3. FXAA:             {path_fxaa} (Size: {os.path.getsize(path_fxaa):,} B)")
    print(f"  4. HDR Bloom + ACES: {path_hdr} (Size: {os.path.getsize(path_hdr):,} B)")
    print("=" * 70)


if __name__ == "__main__":
    main()
