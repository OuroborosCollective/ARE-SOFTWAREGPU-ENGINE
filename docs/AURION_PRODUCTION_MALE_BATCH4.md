# Aurion production male GLB originals — batch 4 (2026-10-09)

The owner identifies these eight exact uploaded GLBs as the revised **original Aurion models**. This is a statement of **source asset provenance**, not an independently verified active server deployment. Exact SHA-256 hashes, byte lengths, source names, rig/animation hashes, model sizes, LOD mapping and warnings are pinned in `fixtures/aurion/npc_production_male/manifest.json`.

| Family | High/LOD1 | Medium/LOD2 | Low/LOD3 | Mobile/LOD4 |
|---|---:|---:|---:|---:|
| Universal Male Buzzed, triangles | 441 | 256 | 120 | 57 |
| Base Male EquipmentSlots, triangles | 417 | 242 | 114 | 53 |
| Maximum texture dimension | 1024 | 512 | 256 | 128 |

All eight original GLBs were independently parsed locally and had proper GLB2 signatures, **65 skin joints**, 7 real animation clips / 195 channels per clip, and normalized skin weights. Their skeletal and animation stream SHA-256 digests are identical within each four-LOD family. The new Base Male rig and seven clips also match the two previous Base_Male_L0/L1 fallback files byte-for-byte at the accessor stream level. Explicit 9 equipment slots occur in Base Male, not Universal Male.

**New defect candidate detected using independent CPU linear-blend-skinning replay on the original binaries:** Mobile LOD4 in both families has no skin vertex influences assigned to the `lowerarm_l` and `lowerarm_r` joints, despite four changing arm joint rotation tracks in the `Attack 2` clip. High LOD1 contains approximately 13.00 total vertex weight per forearm. The Mobile attack's observed maximum mesh displacement from idle t=0 is ~0.009 units, versus ~0.536 units at High in both families; this is an independent geometry diagnostic, not a confirmed Aurion runtime rendering defect or evidence of gameplay harm.

**Aurion LOD compatibility:** `Echoes_of_Aurion/shared/glbImportContract.ts` accepts catalog logical levels `0,1,2,3`, whereas physical source names advertise `LOD1,LOD2,LOD3,LOD4`. An explicit **source-only** proposed mapping is High 1 → catalog 0, Medium 2 → 1, Low 3 → 2, Mobile 4 → 3. This manifest **does not alter** existing server catalogs/assignments, choose models for players, or introduce an unsafe parser shortcut. Aurion's `AnimatedGlbActor` also has no explicit `cast` pose for the confirmed `Cast Spell` clip; an isolated future patch with tests would be needed to add it.

The binary GLBs are deliberately not silently substituted into public GitHub CI. CI tests manifest validity and negative paths; exact byte inspection and CPU pose replay were performed locally against original owner-provided binaries. Full skinned visual equivalence requires Aurion's runtime renderer on the same scene/camera at multiple animation times, approved-asset SHA readback from the **live** catalog and actual frame timings. Source metadata `catalogCompatible: true` cannot prove deployed status. Leave Aurion world authority, NPC decision model and 100-ms tick entirely untouched.

**No ScaNN and no GPU were used.** The previous fallback fixtures remain intact. Issue #6 remains open until true runtime and original-file evidence.
