# Slice C: AeroRaster-scale reproduction benchmark (5 120 triangles) + batch triangle setup

Date: 2026-10-10. All numbers from this development container (Python 3.12.12,
numpy 2.2.5, single-threaded deterministic runs) through the Phase-4 worker
receipt harness — bounded single-host samples, not hardware-independent
promises. Fixture: `fixtures/aurion/phase4_offline/job.scene5k.example.json`
(seeded procedural mesh, rings 32 × segments 80 = 5 120 triangles,
`mesh_sha256` pinned in the receipt).

## Why this slice

The 400-triangle Phase-4 fixture understates setup cost. At AeroRaster scene
scale (~5k triangles) the profile before Slice C was:

| Stage (128 px, tiles backend, 5 120 tris) | Time | Share |
| --- | --- | --- |
| `prepare_triangles` (vertex stage + clip + screen map) | 524 ms | 42 % |
| — of which `clip_triangle` alone | 360 ms | 29 % |
| `rasterize_tiles` (binning + coverage + shading) | 722 ms | 58 % |
| — of which the binning loop | 50 ms | 4 % |

The dominant setup cost was the per-face Python Sutherland–Hodgman machinery
running on scenes where **no** triangle crosses a plane — exactly the
amortization target of AeroRaster's/GLimpSW's batched two-step setup.

## Change: vectorized fast path in `prepare_triangles` (geometry.py)

Plane distances (all 7 homogeneous planes), perspective divide, screen mapping
and the signed area are now evaluated as whole arrays over all faces. Only
faces that actually cross a plane (or hit a discarded vertex / non-finite
screen position / degenerate area) enter the unchanged per-face clipping slow
path. Vertex shader callbacks stay per-vertex (arbitrary Python, cannot be
batched safely). Error behavior (`IndexError` on malformed/out-of-range
indices, fail-closed discards) is unchanged.

Bit-identity is pinned by `test_prepare_triangles_setup.py`: a verbatim copy
of the original implementation serves as oracle; equivalence is stressed
across 12 seeds × 4 zoom levels (two forcing real clipping) × 2 aspect ratios,
plus NaN-discard parity, attrs-object sharing and end-to-end render digests
on both backends.

## Measured results

Setup stage alone (`prepare_triangles`):

| Scene | Original | Batched | Speedup |
| --- | --- | --- | --- |
| 400 tris | 41.4 ms | 3.6 ms | **11.56×** |
| 5 120 tris | 514.1 ms | 42.1 ms | **12.21×** |

End-to-end (setup + tiles rasterization, byte-identical color+depth):

| Scene | 128 px | 256 px |
| --- | --- | --- |
| 400 tris | 1.23× | 1.08× |
| 5 120 tris | **1.60×** | 1.26× |

Official Phase-4 gates after Slice C (worker receipts, bands = existing CPU
reference path, byte-identity required):

| Fixture | bands | tiles | Speedup | Decision | Receipt |
| --- | --- | --- | --- | --- | --- |
| `aurion_phase4_seedmesh` (400 tris, 128 px) | 348.223 ms | 111.339 ms | **3.1276×** | activate | `71eb0e88…` |
| `aurion_phase4_scene5k` (5 120 tris, 128 px) | 1790.981 ms | 750.608 ms | **2.386×** | activate | `48de87fa…` |

Gate progression over the slices on the 400-tri fixture: 1.9375× (pre-B) →
2.6213× (Slice B) → 3.1276× (Slice C).

## Claims check vs. the literature

| Claim (source) | Our measurement | Verdict |
| --- | --- | --- |
| Batched/SoA triangle setup amortizes per-face overhead (AeroRaster, GLimpSW two-step setup) | setup 11.6–12.2×, e2e up to 1.60×, byte-identical | **confirmed transferable**, integrated |
| Early/full-tile coverage culling culls >90 % of raster work (OpenSWR) | Slice B: full tiles ≤1 % of bins, net 0.98–1.01× | **not reproducible** in a scalar-fragment architecture; not integrated |
| AVX2/AVX-512 SIMD inner loops give 30–50 %+ (Kayhan, GLimpSW) | not testable in the scalar NumPy fragment stage; the GIL-free `tiles-jit` LLVM kernel is the only SIMD path here | **remains a literature claim**, no own evidence — do not cite as our result |

## Limits

- The vertex stage is still per-vertex Python (arbitrary shader callbacks);
  a batch shader API is a possible future contract addition, not done here.
- The fragment stage is still scalar per pixel; beyond 256 px it dominates
  again. Any further large win requires compiled fragment kernels, which is a
  separate determinism review (fastmath must stay off).
- Numbers are single-host; CI reruns the fixture gates, not this 5k breakdown.
