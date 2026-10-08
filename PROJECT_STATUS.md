# ARE SoftwareGPU Engine - Evidence status (2026-10-08)

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
- No native Windows D3D11/DirectX interoperability, CUDA driver API compatibility, arbitrary-language runtime support or productive LLM/GPU training is established.
- Android Kotlin code and Android hardware runtime have not been validated by an Android device/emulator CI run.
- Multilingual clients are prototypes; not all language ABIs have compilation/interop regression coverage.
- Benchmarks are not independently validated against Mesa llvmpipe, WARP or other CPU baselines.
- **Network service NOT production-safe**: no required authentication/TLS, access policy, payload/memory/CPU quotas or deadline enforcement; do not expose off-loopback.
- Missing published license decision; do not claim open-source grant merely because the repository is public.
- Aurion read-only offline-worker contract is documented, **not yet integrated** into the Aurion game runtime.

## Release gate
The PR remains **Draft** pending network hardening, stronger cross-platform/Android and real workload evidence, and owner approval for merge. This document records tested capabilities, not a claim of universal GPU replacement.
