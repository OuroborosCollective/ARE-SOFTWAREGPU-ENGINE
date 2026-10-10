# Aurion Phase 4: isolated offline render/benchmark worker (issue #6)

Status: implemented in this repository as **offline tooling**. No Aurion
runtime connection is established or authorized by this document.

## Scope and authority

The worker renders revisioned fixtures into derived artifacts and receipts.
It has **no** authority over canonical world state, NPC/physics, gameplay
persistence or the 100-ms game tick, and it does not open any network
service. Isolation is a killable child process, not a container requirement.

## Input contract: `are.aurion.offline-render-job.v1`

| Field | Rule |
| --- | --- |
| `protocol` / `authority` | exact strings; `authority` must be `offline-read-only` |
| `fixture.kind` | `procedural` (seeded deterministic mesh) or `glb` (SHA-256 pinned glTF2 binary via the Phase-1 loader) |
| `fixture.fixture_id` | `[A-Za-z0-9_-]{1,64}`, used for artifact naming |
| `fixture.seed` | integer `0..2^31-1`; mesh derived by SHA-256 counter-mode PRNG (no numpy RNG), digestible via `mesh_sha256` |
| `fixture.rings` / `fixture.segments` | `2..64` / `3..128` (max 8 320 vertices / 16 384 triangles) |
| `fixture.file` / `fixture.entry` (glb) | filename allowlist; entry pins `bytes`, `source_sha256`, `vertices`, `triangles`, `meshes`, `materials`, `images` |
| `camera` | `yaw_degrees ±180`, `pitch_degrees ±85`, `center_y ±100`, half extents `0.001..200`; NaN/inf rejected |
| `render.pixels` / `render.repeats` | `32..256` / `2..5` |
| `render.backend` | `tiles`, `tiles-jit`, `bands` |
| `budget.deadline_seconds` | `0.02..300` wall-clock, parent-enforced |
| `budget.memory_mb` | `32..4096` |
| `budget.cpu_seconds` | `0.05..600` |

Example: `fixtures/aurion/phase4_offline/job.example.json`.

## Output receipt: `are.aurion.offline-render-receipt.v2`

Every run — success **or failure** — writes `aurion-phase4-receipt.json`:

- `job_sha256`, `repo_revision`, `python`, `os` (input + source binding)
- `outcome.fixture.mesh_sha256`, `vertices`, `triangles` (derived input digest)
- `outcome.replay_hash_sha256` + `repeat_byte_identical`: SHA-256 over color+depth
  must be identical across all repeats, otherwise the run fails closed
- `outcome.image_bmp_sha256`, `covered_pixels`
- Resource receipts: `samples[].wall_ms/cpu_ms`, `median_wall_ms`,
  `cpu_seconds_total`, `peak_rss_bytes` (Linux `ru_maxrss`; `null` elsewhere)
- `budget_compliance.{deadline_ok,memory_ok,cpu_ok}`
- `errors[]` with stable error classes; `receipt_sha256` over the canonical body

## Isolation model

1. Parent validates the job (fail-closed, specific codes) **before** spawn.
2. Child is `python _offline_child.py` — a stdlib-only bootstrap that applies
   `RLIMIT_AS` (RAM) and `RLIMIT_CPU` (kernel backstop at 2× budget) **before**
   importing numpy/software_gpu. Known boundary: the kernel RAM limit is set
   at `max(budget, 512 MiB)` because CPython+OpenBLAS cannot reliably start
   below that (allocation failure inside native threadpool init hangs instead
   of raising). The contractual budget is additionally enforced fail-closed
   by the parent through the child-reported peak-RSS receipt
   (`WORKER_MEMORY_BUDGET_EXCEEDED`).
3. Deadline: parent `wait(timeout)`; on expiry the child is terminated/killed
   and the run fails with `WORKER_DEADLINE_EXCEEDED`.
4. CPU: cooperative `process_time()` check before every repeat
   (`WORKER_CPU_BUDGET_EXCEEDED`); death by `SIGXCPU` maps to
   `WORKER_CPU_LIMIT_EXCEEDED`.
5. GLB input is re-hashed byte-for-byte (`SOURCE_SHA256_MISMATCH`), filenames
   are allowlisted and resolved inside `--model-dir` (`MODEL_PATH_ESCAPE`).

## Evidence: negative contract tests (`test_aurion_offline_phase4.py`)

| Test | Expected failure |
| --- | --- |
| 15-case input matrix (seed/rings/pixels/repeats/backend/budget/camera/NaN) | specific codes, pre-spawn |
| deadline 0.02 s | `WORKER_DEADLINE_EXCEEDED` + failure receipt written |
| memory 32 MB (< real ~48 MB peak) | `WORKER_MEMORY_BUDGET_EXCEEDED` |
| cpu 0.05 s (< interpreter startup) | `WORKER_CPU_BUDGET_EXCEEDED` |
| GLB hash mismatch / name escape | `SOURCE_SHA256_MISMATCH` / `GLB_NAME_INVALID` |
| replay equality across two identical isolated runs | identical `replay_hash_sha256` |

## Benefit gate vs. the existing CPU path

`compare_backends` renders the identical scene through the historical `bands`
renderer (the repository's existing CPU reference path) and the `tiles`
backend, sequentially, single-threaded. `decide_activation` returns
`activate` only if color+depth are **byte-identical** and the measured
speedup meets the threshold (default 1.10×); otherwise `hold` — per the
issue contract, no benefit means no activation.

Measured on this development container (Python 3.12.12, numpy 2.2.5,
single worker, fixture `aurion_phase4_seedmesh`, 128 px, 3 repeats):

| Backend | Median wall | Result |
| --- | --- | --- |
| bands (existing CPU path) | 305.376 ms | reference |
| tiles | 157.613 ms | **1.9375× faster, byte-identical image** |

Decision in receipt: `activate` (`REAL_BENEFIT_ON_IDENTICAL_IMAGES:1.94x`).
Bounded single-host sample, not a hardware-independent promise; CI reruns the
same gate via `aurion-offline-glb.yml` on Linux+Windows.

## Research-backed optimization roadmap (next slices)

Grounded in current software-rasterization practice and 2024–2026 work:

1. **Two-step triangle setup + packet/mask binning** (GLimpSW, AVX-512):
   early step does perspective divide, fixed-point snapping, bbox and
   back-face/degenerate culling; bins store packet IDs + coverage masks
   instead of per-triangle pointers — much lower binning overhead.
2. **Early coverage culling**: OpenSWR culls >90 % of triangles with a quick
   pre-rasterization coverage-mask pass before binning; directly applicable
   to `tile_backend.py`.
3. **L2-resident tile depth buffers** (ryg's rasterizer series): size tiles
   so the tile depth buffer stays in L2; combine with 2×2-quad SIMD setup
   (SSE/AVX batches of 4+ triangles). Measured 30–50 % from AVX in
   tile-based rasterizers (Kayhan).
4. **Texture swizzling**: 8×8 tiled texture layout reduces TLB misses ~32 %
   and unused prefetches ~36 % vs. linear (GLimpSW measurements) — relevant
   once texturing lands.
5. **Meshlet/cluster LOD + two-pass HZB occlusion** (Nanite lineage, also
   CuRast 2026): cluster-based culling with a hierarchical Z-buffer fits the
   Aurion LOD fixtures already pinned in this repo; software raster of
   sub-32 px clusters beat hardware paths ~3× in Nanite's measurements.
6. **Visibility buffer + deferred attribute resolve**: render primitive IDs
   first, shade later; keeps the raster core branch-light and enables the
   triangle-attribute cache (RLE compress/expand, 8–16 % resolve speedup in
   GLimpSW).
7. **Numba `prange` / ISPC evaluation** for the barycentric+depth inner loop
   beyond the current coverage kernel, keeping `fastmath=False` determinism.

## Not established

- No PBR/texture equivalence with Aurion's real renderer
  (`texture_pbr_equivalence: false`, receipt field
  `pbr_or_aurion_renderer_equivalence: NOT_ESTABLISHED`).
- Windows/macOS have no rlimits; resource receipts there rely on the
  cooperative CPU check and the parent deadline only.
- No network path (Phase-3 dependency) and no gameplay-facing activation.
