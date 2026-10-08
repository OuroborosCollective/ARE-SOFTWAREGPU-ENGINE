# Issue #3 — Raster correctness contract and limits

This change addresses the documented clipping/coverage discrepancies in the CPU rendering path. The original renderer rejected an **entire** triangle if any vertex had `w <= 0.01`; a partially visible triangle could disappear. Shared edges previously used inclusive `>= 0` on both neighboring triangles, allowing the same edge sample to be shaded twice.

## Shared geometric contract

- **Coordinates:** clip-space `[-w,w]` in X, Y, Z (OpenGL-style projection used by the included `Matrix4.perspective`), not native DirectX clip semantics.
- **Clipping:** Sutherland–Hodgman against all six homogeneous planes and a positive-W safety plane. Intersections interpolate clip positions and array-valued varyings in clip space, then triangulate convex clipped polygons.
- **Validation:** non-finite clip coordinates and array varyings are rejected; malformed/out-of-range indices raise errors; zero-area/back-facing primitives are discarded.
- **Coverage:** all CPU pipelines (bands, tiles, tiles-jit, MSAA) use the same positive-winding **top-left** edge rule; equal-depth fragments retain existing depth ownership because depth compare is strictly `<`.
- **Interpolation:** screen-space barycentric interpolation with inverse-W correction for array-valued shader parameters. Scalar varyings follow the project's legacy flat interpolation behavior.
- **Sample conventions:** standard renderer tests pixel centers; 4x MSAA tests subpixel offsets and updates only covered passing depth samples. The FXAA pass remains a screen-space filter of the resolved color buffer.

## Tests

`software_gpu/tests/test_issue3_clipping.py` drives real `Framebuffer`, `SoftwareRasterizer`, `MSAAFramebuffer` and `MSAARasterizer` paths.

1. A partially near-clipped triangle **must survive** and generate visible depth; bands and tiled CPU paths must agree.
2. Nonfinite vertices, entirely clipped primitives, and a zero-W triangle must not write invalid pixels.
3. A rectangle composed of adjacent triangles must cover every pixel exactly once under the top-left rule.
4. MSAA near-clipped geometry must produce real covered subpixel samples and finite resolved depth.
5. Existing tile/band/JIT/FXAA/postprocess regressions and runtime demo tests must remain green in the Linux/Windows matrix.

## Explicit limits

The implementation is a **CPU-only experimental rasterizer**. It does **not** establish complete Direct3D conformance, clipping against user-defined planes, derivative-dependent shader semantics, order-independent transparency, native fixed-point GPU rasterization rules, or bit-identical floating-point results across arbitrary CPUs. Do not publish benchmark speedup claims for these changes without new results on the revised renderer.

No public HTTP/TCP service or Aurion live-physics/100-ms-tick integration is part of Issue #3.
