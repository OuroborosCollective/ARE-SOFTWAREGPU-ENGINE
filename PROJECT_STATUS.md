# ARE SoftwareGPU Engine - Evidence status (2026-10-10)

## Integrated source
- Owner-supplied SoftwareGPU 1.2.0 TAR pinned to SHA-256 `b8b44a39b46ecfb50a2de121b2534c5d9912fccda2b1b0475faf194fe8e589b8`.
- GitHub importer accepted and committed **62 UTF-8 source files**; rejected compiled caches, generated BMP/PPM and TAR links. Individual upstream hashes are preserved in `evidence/source-manifest.json` (import provenance, not hashes of later patches).
- Import GitHub Actions: https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/37823687557 (**passed**; 22 original tests, source readback 62/62).
- CPU regressions: https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/37824923372 (**passed**; Linux Python 3.11/3.12: 27 tests; Windows Python 3.11/3.12: 27 tests with one explicitly skipped Linux/Android Unix socket test; wheel build, installed CLI outside checkout passed).

## Corrections included
1. MMORPG swarm speed limiting updates the actual device-backed velocity buffer, consistent with displacement; real negative regression added.
2. Python package includes `main.py` in distributable wheel; CLI smoke-tested outside source checkout.
3. Output files of CPU renderers, image tools and benchmarks use portable paths (default current working directory, optional `ARE_SOFTWAREGPU_OUTPUT_DIR`).
4. Unix-domain socket test is skipped only where the operating system does not support the required POSIX socket semantics, instead of treating missing Windows `AF_UNIX` as a renderer failure.

## Surface classification
- **Core**: virtual CPU memory, cooperative executor, compute kernels, framebuffer and rasterizer.
- **Production candidates**: standalone Python CLI, HTTP/TCP interface, cross-language sample clients, mobile examples.
- **Tests/evidence**: CPU regression suites, CI workflows, upstream source manifest and archived original README.
- **Effects**: optional file exports, benchmark reports and network responses. No authority to mutate Aurion.
- **Persistence**: generated local files only; no canonical world-state or durable database owner.
- **Runtime projections**: derived images/metrics; a checked-in adapter is not proof of live deployment.

## Unproven or blocked
- **No performance parity or superiority versus gaming/discrete GPUs is established or even claimed.** Every speedup number in this repository is CPU-vs-CPU (historical band renderer reference or Mesa llvmpipe software GL). The MIHA literature review (2026-10-10) confirms: no published CPU rasterizer demonstrates gaming-GPU parity; claims of "GPU replacement" would be unsupported by both our measurements and the cited literature.
- No native Windows D3D11/DirectX interoperability, CUDA driver API compatibility, arbitrary-language runtime support or productive LLM/GPU training is established.
- Android Kotlin code and Android hardware runtime have not been validated by an Android device/emulator CI run.
- Multilingual clients are prototypes; not all language ABIs have compilation/interop regression coverage.
- CPU benchmarks are cross-checked against Mesa llvmpipe in CI (runs 37852483597/37852483674); they remain single-host measurements, not independently audited hardware comparisons.
- **Network service NOT production-safe**: no required authentication/TLS, access policy, payload/memory/CPU quotas or deadline enforcement; do not expose off-loopback.
- Licensing proposal now documented: PolyForm Noncommercial 1.0.0 plus `Required Notice:` attribution and separate written commercial licensing; this is source-available, not OSI-open-source. Verify provenance and third-party rights before granting commercial rights.
- Aurion read-only offline-worker contract is implemented in this repo (Phase 4, issue #6, PR #16), **not yet integrated** into the Aurion game runtime (separate repository, separate decision).

## Research-backed CPU optimization (2026-10-08)
- **Tiles**: true 2-D binning with immutable triangle order per tile; disjoint framebuffer ownership and NumPy-vectorized barycentric/depth masks. The previous band renderer remains selectable for differential verification.
- **Optional LLVM**: `software_gpu[jit]` enables a Numba-compiled CPU coverage kernel with `nogil=True`, `fastmath=False`; Python fragment shaders remain scalar callbacks. This does not claim SIMD machine-instruction verification.
- **MSAA**: exact 4x `uint16` resolve removes an unnecessary float32 copy, and unsupported sample counts fail closed.
- **Regressions**: baseline 31 tests, optional JIT 33 tests. Deterministic image/depth comparisons across tile sizes and CPU thread counts, Windows/Linux Python test matrix, wheel/CLI smoke.
- **Evidence**: https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/37834676696 (all jobs successful at source SHA `a14be371f60c4dcb8243d4f47bcacc56cba95ce8`).
- **Measured CI samples**: NumPy tiles: 1.51–1.57x versus historical band renderer (single worker). Optional JIT tiles: 1.65–1.73x versus band renderer (two workers). All three deterministic fixtures produced identical frame color and zero depth error in those runs. **These are bounded measurements, not hardware-independent performance promises**. See `docs/RENDER_OPTIMIZATION_EVIDENCE.md`.

## Measured optimization slices (2026-10-10, issue #6 harness)
All gated on byte-identical color+depth plus >=1.10x speedup against the bands
reference ("no benefit => no activation"); details in
`docs/AURION_PHASE4_OFFLINE_WORKER.md` and `docs/AERORASTER_REPRO_BENCHMARK.md`:
- **PR #16** — Phase-4 isolated offline render/benchmark worker (issue #6):
  subprocess isolation with pre-import rlimits, replay/peak-RSS/CPU receipts,
  negative deadline/memory/CPU/input tests, benefit gate in code.
- **PR #17** — raster correctness contract: analytic perspective ramp, depth
  tie-break, fail-closed numerics, alpha non-goal pinned (9 tests).
- **PR #18** — vectorized varying interpolation (1.27–1.93x) and worker tile
  size 32 (measured 8/16/32/64 matrix); OpenSWR-style full-tile culling
  measured and **rejected** (0.98–1.01x, documented negative result).
- **PR #19** — batch triangle setup in `prepare_triangles` (setup 11.6–12.2x,
  e2e 1.08–1.60x, oracle-pinned bit-identity); AeroRaster-scale 5 120-triangle
  fixture with own receipts. Worker gate: 3.1276x (400 tris) / 2.386x (5k).
- Not established: texture/PBR equivalence, SIMD fragment shading (scalar
  NumPy stage cannot validate the literature's AVX2 claims), alpha blending
  (pinned as a non-goal).

## Merge versus production gate
The owner authorized merge of tested, CPU-only research changes into this standalone repository. **No public service or Aurion runtime deployment is authorized by merging.** Network authentication/quotas, Android device validation, native GPU API compliance and license selection remain separate release blockers.
