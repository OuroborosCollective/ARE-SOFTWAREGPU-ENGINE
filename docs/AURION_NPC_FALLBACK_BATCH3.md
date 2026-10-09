# Aurion NPC fallback GLB batch 3 — original evidence

**Authority:** offline-read-only; no NPC world-state, live animation or engine replacement.

On 2026-10-09 the owner supplied ten original GLB2 files: five NPC variants, with **exactly the available LOD0 and LOD1** per variant. Their source SHA-256 hashes, byte sizes, triangle counts, skeleton/animation stream digests, equipment metadata and per-family differences are pinned in `fixtures/aurion/npc_fallback/manifest.json`.

| Family | LOD0 tris | LOD1 tris | Reduction | Explicit `Slot_` nodes |
|---|---:|---:|---:|---|
| Base Male | 1479 | 643 | 56.5% | Nine |
| Reference Female SimpleParted | 1337 | 734 | 45.1% | Nine |
| Reference Male SimpleParted | 1234 | 701 | 43.2% | Nine |
| Universal Female Buns | 1492 | 795 | 46.7% | None |
| Universal Female Buzzed | 1488 | 713 | 52.1% | None |

## Verified facts from real original binaries

- Each file contains one skin with **65 joints**, inverse bind matrices, and seven animations: **Attack 2, Cast Spell, Death, Fight, Idle, Run, Walk**.
- Each animation contains 195 channels (65 translation, 65 rotation, 65 scale); sampler inputs/outputs use STEP and LINEAR interpolation, with verified finite timestamps and consistent lengths.
- All five LOD0–LOD1 pairs have **identical rig structure and animation accessor-byte streams**. Lower-detail geometry does not appear to alter the rig or clips. The stream and rig content hashes are pinned separately from the enclosing GLB file hash.
- Actual vertex `JOINTS_0` and `WEIGHTS_0` streams exist for skinned primitives. Weight sums are within 1.8e-7 of one in the inspected files.
- The three *Base-/Reference*-variants explicitly expose nine `Slot_` nodes (hand, main hand, shield, shoulders, chest, head, legs), with `extras.equipment_slot` and their declared attachment-parent bones. The two *Universal Female*-variants do **not** provide these explicit slot nodes, although skeletal bones are present. They must not be reported as validated equipment socket-compatible.
- Some slots are attached to semantically surprising parent bones (e.g. `Slot_Head` and `Slot_Legs` are parented to `pelvis` in the Base/Reference assets). This is a **recorded asset behavior**, not corrected or assumed to be an intended anatomical socket.

## Verification

The CPU-only `npc_fallback_audit.py` verifies the **real input bytes**, not just JSON metadata. It checks SHA-256 of the exact original file, glTF/GLB framing, bounded binary accessor spans, node parent/slot metadata, skin indices, inverse bind matrices, normalized skin weights and the channel stream SHA. It produces a digest-bound JSON receipt.

```bash
python -m software_gpu.integrations.aurion.npc_fallback_audit \
  --manifest fixtures/aurion/npc_fallback/manifest.json \
  --source-dir /path/to/original-npc-glbs \
  --output /tmp/aurion-npc-audit.json
```

**Critical boundary:** the 10 large original GLBs are **not** checked into the GitHub repository or available on public GitHub runners. GitHub CI covers manifest validation, negative inputs, CLI and existing render regressions; CI green is *not* proof that a GitHub runner audited all ten originals. Initial source inspection and semantic-LOD byte comparison were performed against the user-supplied original local GLBs.

**Still unproven:** actual software-skinning of all clips into pose snapshots, animation trajectory correctness, visual PBR equivalence with Aurion's WebGL/WebGPU renderer, equipment placement quality, speedup or gameplay FPS. Those require separate real CPU animation/skeleton render work and direct Aurion-reference evidence; no GPU acceleration or ScaNN has been added.

Issue #6 remains open while original-assets rendering and comparative benchmarks are unresolved.
