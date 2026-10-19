# SpherePop–CAG–Doppler: object-accurate CPU projection (experimental)

**Authority:** isolated native C++17 CPU research. `main` remains unmodified by this branch until exact-head CI succeeds. This does **not** enable any gameplay, animation, audio or production shader effect.

## Integration surface

`native/raster/spherepop_object_mask.hpp` extends the merged [PR #125](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/pull/125) profile while retaining its original single-object API and Wolfram/CAG classical Doppler oracle.

For each object, save a float32 depth snapshot, perform its **real** native raster draw, then call `label_depth_winners(before, after, cells, object_id, owner_ids, cells)`. Only strictly nearer depth updates may write the owner ID. Equal-depth submissions preserve the first owner; invalid or nonmonotone depth rejects the entire update before any owner is modified.

Once the scene is complete, invoke `apply_object_masked` with the final RGBA8 framebuffer, float32 depth and full uint32 owner map. It constructs an isolated per-object depth visibility projection, delegates to the existing deterministic classical Doppler tint and appends the same SpherePop-inspired Bind/Pop/Collapse events; Refuse remains available. Background and other object IDs, alpha, original depth and owner map stay unchanged.

## Tests and boundaries

- `native/raster/spherepop_object_mask_native_test.cpp`: **two real native C++17 raster draws**, overlapping geometry, strict depth-tie priority, object effect isolation, replay, negative cases.
- `native/raster/spherepop_object_mask_contract_test.cpp`: transactional negative transition, type/buffer/finite-depth admission, stable event fingerprints, colored-pixel count and owner isolation.
- `software_gpu/tests/test_spherepop_object_mask_native.py`: compiles and executes both source programs using the repository's compiler flags. They run in the existing Linux/Windows CPU-regression test discovery; missing compiler is failure, never silent skip.
- Native mutation stays opt-in. No calls to Wolfram in the render loop; no copied SpherePop source or claim that a short event log implements the full SpherePop calculus.
- The history fingerprint is FNV-1a, **not a cryptographic evidence digest**.
- Projection allocates one float32 temporary per pixel (4 bytes/pixel); no measured speedup or GPU parity is claimed.
- **No original uploaded GLBs committed.** Existing GLB import remains unchanged; original Aurion asset rendering and multimodel frame benchmarks are still required before production activation. The prior local 49-monster import-integrity check demonstrates valid geometry, not this effect's end-to-end correctness.
- Caller supplies disjoint RGBA/depth/owner buffers, immutable snapshots and serialized draw ordering. Do not pass aliased pointers or concurrently modified memory. An owner map must not be inferred from an arbitrary already-composited image.

## Required acceptance

```bash
python -m unittest software_gpu.tests.test_spherepop_object_mask_native -v
python -m unittest discover -s software_gpu/tests -p 'test_*.py' -v
```

Verify exact commit-head full CPU/Windows/LLVM/Mesa CI, regression coverage floors, final append-only `Memory.md` receipt and merge readback. Then start a separate source-bound GLB replay and at least 15 CPU repetitions for performance; do not substitute static GLB metadata for actual rendered output.
