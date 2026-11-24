# Issue #295: GLB2/WorldForge admission security and evidence limits

**Scope:** offline importer and geometry review only. No active world/gameplay writes, no renderer/kernel change, no new glTF/FBX feature support.

## Exact reached paths and ownership

| Surface | Code | Ownership / status |
|:--|:--|:--|
| Production/offline importer | `software_gpu/integrations/aurion/offline_lod_worker.py` | SHA- and size-pinned GLB2 JSON/BIN, real typed NumPy accessors, static silhouette path |
| Production/offline model input | `software_gpu/research/model_probe.py` | Separate SHA-pinned GLB2 -> AREMDL01/02/03, one indexed mesh primitive, optional bounded PBR skin |
| Core/native | `native/symbolic/model_main.cpp` | C++17 decodes **typed AREMDL01/02/03**, **not** raw FBX/glTF; therefore no Assimp/fastgltf native sanitizer finding can be claimed |
| Effects | `software_gpu/integrations/worldforge.py` | RGB silhouettes/BMP previews, SHA-bound image outputs |
| Persistence | WorldForge receipt/report directory | Version + job + source/receipt SHA identity and cache replay validation; staging in temporary directory |
| Runtime projection | Aurion offline workers | Subprocess with deadline; **not** the live 100 ms/10 Hz simulation |
| Tests | `software_gpu/tests/test_glb_admission_security.py` | Real GLB2 bytes generated in each test, negative source and cache tests, **synthetic fixtures** |

No reachable ARE FBX parser, Assimp or fastgltf dependency was found on the audited `main` revision `58fbe4178a68127a2398fcd3eb86fbfdaa8781ab`. The linked Assimp/fastgltf upstream reports in Issue #295 are **reference threats, not reproduced ARE vulnerabilities**. The original privately supplied FBX assets are not a reproducible in-repository FBX import test.

The protected GLB2 container preflight `tools/glb_container_preflight.py` remains byte-identical. The opt-in unratified GLB3/glTF2.1 sandbox remains an inspection tool, not an importer.

## New admission gates

- Before any geometry arrays are allocated, check a real SHA-256-pinned GLB2 with the existing **8 MiB file** and **128 KiB JSON** limits, framing and chunk types.
- Reject nested duplicate JSON keys, non-finite JSON constants, invalid Unicode/JSON and JSON nesting **deeper than 64**. Traversal is iterative to avoid unbounded Python recursion.
- Require a single embedded GLB2 BIN record with a **non-boolean, nonnegative integer** `byteLength`, allowing at most three GLB padding bytes. Check all declared bufferView byte ranges against the **declared** BIN size, including unused views.
- Reject any external `buffer.uri` or `images[*].uri` in this strictly offline subset; no URL resolution/downloads.
- Retain existing **128 nodes**, **32 meshes**, **128 accessors/views**, **25k vertices**, **25k triangles**, scene expansion **1024 visits** and node traversal **depth <= 8** gates. The typed model/PBR path retains its own separate budgets.
- SHA-recheck a cached WorldForge source before reusing an existing report. Check the report's schema/engine/job/receipt/model identity and all six preview BMP SHA-256 values (if status=reviewed); reject tampering or changed source rather than returning a stale success.
- Only known valid-but-unsupported geometry states may write `manual-review`; corrupt GLB framing, invalid accessors/metadata and source mismatches abort without publishing `report.json`. Fresh reports are staged and atomically renamed.

### WorldForge sources beyond the review budget

The review and incremental scan check the real regular-file size against the
export receipt before opening the model or looking up a geometry report. A
matching source larger than 8 MiB is **not admitted**. It produces the separate
`are.worldforge.admission.v1` diagnostic with `GLB_REVIEW_SIZE_LIMIT`,
`sourceHashVerified: false`, `geometryReviewed: false` and
`manualReviewRequired: true`. `receiptSha256` identifies the receipt bytes;
`declaredModelSha256` is only the exporter's claim and is not a verified source
hash. Neither the GLB container nor its geometry has been validated.

The Python `review()` API raises `WorldForgeBudgetRefusal` (a `ValueError`) for
this result. Both CLI actions print its JSON diagnostic; `scan` continues to
other jobs without consuming a geometry-review slot. Completing that scan does
not admit the oversized input. No geometry report is created or reused for this
state, and existing reports are left untouched. Each repeated scan checks the
receipt and source metadata again, without hashing the oversized source. A
same-size content change therefore remains rejected and unverified, not a
claimed hash match. Missing files, symlinks, size mismatches and bounded-input
hash or parser failures still fail the scan. A subsequently smaller source must
pass normal size, hash, parser and cache checks before producing a review.

These are admission/receipt safeguards, **not** proof of general glTF compatibility, complete parser fuzzing or renderer parity for 100/1300/3500-mesh scenes.

## RED / positive baseline / CI

Real Linux/Python 3.11 baseline: [CPU regressions 44972450980](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/44972450980), commit `b05c0e9a6eff6e3e7b22ca7822ac92c137f28aed`. **7 failures intentionally reproduced**: invalid (-1, bool, 2^32, 2^64-1) BIN lengths, external image URI, deep JSON, stale SHA cache. The 55-byte malformed GLB, extreme accessor counts and valid SHA-pinned one-mesh geometry already failed/passed appropriately on the baseline. These generated bytes are **not** upstream Assimp/FBX PoCs.

The updated regression additionally checks duplicate JSON keys, 100/200-node scene chains, no false review receipts after a rejected import and tampered output BMP. A positive real CPU WorldForge 6-image output, original GLB2 geometry and SHA repeat are exercised in `test_worldforge_release.py` and `test_aurion_offline_lod.py`. Legacy `test_glb_import_resource.py` checks 100 large/small import/release cycles, real RGB/Float32-depth replay and Python heap budgets.

```bash
python -m unittest software_gpu.tests.test_glb_admission_security software_gpu.tests.test_glb_import_resource software_gpu.tests.test_aurion_offline_lod software_gpu.tests.test_worldforge_release -v
python -m unittest discover -s software_gpu/tests -v
```

The dedicated `.github/workflows/issue295-glb-security.yml` executes the first command on Ubuntu/Windows and Python 3.11/3.12. Standard CPU regressions and the existing native/model and Mesa suites remain separate.

**Truth boundary / not verified here:** true FBX PointsIndex decoder, Assimp/fastgltf ASan/UBSan (no local raw-FBX/glTF C++ parser); real independent source model with 65+ joints/morph/material combinations under this **static** LOD importer (unsupported by design); Windows OS-enforced address-space cap (Linux uses `resource.RLIMIT_AS` on its child path); full independent original game-asset fidelity; production/Android runtime memory and FPS; browser or live simulation. A separate native model-input test suite is not an ASan proof of an absent native FBX reader.

**Revisions/evidence:** RED commit/run above; final dedicated- and full-head-CI plus `main` merge SHA must be read back separately. Catalog registration is **not** a measured CPU ranking.
