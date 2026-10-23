# Owner-authorized public GLB batch (20 October 2026)
Ten actual user-supplied Meshy/glTF2 originals, 498,874,792 bytes, 10,140,549 indexed triangles, 39 animation clips across four rigged assets. The owner explicitly states these assets were personally created, are not private, and may be distributed publicly. This is authorization for this supplied batch, **not** a declaration of a specific SPDX license.

## Source identities and reproducibility
- `evidence/owner-public-glb-batch-20261020.json` stores exact ten original SHA-256 hashes, sizes, vertex/triangle counts, clips and image counts. Eight match the earlier original asset manifest by SHA-256; Forest Lord and the small Aurion-rigged model are new to that manifest.
- `python -m tools.owner_public_glb_audit --assets /path/to/originals` performs strictly read-only source SHA and glTF2 structure/count verification. File names are exact and must not be silently substituted.
- Local independent read-only evidence on the supplied original binaries: all 10 pass GLB2 chunk/buffer structure, index bounds, finite geometry, zero exact-area degenerate triangles, finite normals/UV, decodable embedded textures, animation keys, weight normalization and joint-bound checks. No native ARE frame render of this new batch has yet been performed.
- `python -m unittest software_gpu.tests.test_owner_public_glb -v` covers the admission helper's positive and fail-closed negative cases without requiring original binaries in CI.

## Native GPU-free integration gate
The separate native C++17 ARE model loader currently supports SHA-pinned input and bounded 1/4-worker differential native tests. Verify the originals with `software_gpu.research.model_probe` before claiming original-model native parity. For feasible diagnostic smoke start with Aurion Rigged (643 triangles), Assassin (5,000), Log (9,999), Boulder (10,478); then scale to Axe (38,477), Forest Lord (2,292,680) and Wisteria (4,233,077) under explicit RAM and deadline caps. The Axe model exceeds the owner's intended 30k triangles-per-character budget and needs LOD consideration.

Do not infer GPU parity, gameplay FPS, real-time pulse-on-GLB blending, or production deployment from these admission results. The original GLB binaries are not committed by this evidence-only PR; they may be published separately under the owner's authorization with independently checked upload readback.
