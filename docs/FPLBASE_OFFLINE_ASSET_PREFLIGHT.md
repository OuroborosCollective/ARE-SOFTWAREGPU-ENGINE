# FPLBase offline asset preflight

An **optional read-only inspection lane** for the archived [google/fplbase](https://github.com/google/fplbase) FlatBuffers mesh/material dependency format (upstream `4c9f5b751427f3be56a9277497b9078079aa1b9c`, Apache-2.0). This independently written checker does not vendor FPLBase, enable OpenGL, change the CPU rasterizer or introduce any gameplay authority.

Run from the repository root:

```bash
python tools/fplbase_asset_preflight.py --root /trusted/export-root --mesh character.fplmesh --output fplbase-manifest.json
python -m unittest software_gpu.tests.test_fplbase_asset_preflight -v
```

The checker validates selected `FMSH` and `FMAT` FlatBuffer tables, bounds mesh index vectors, resolves required material and texture references **only under a trusted root**, rejects path traversal/symlinks/unknown texture extensions, and creates deterministic JSON with per-file SHA-256 hashes. The JSON is derived offline evidence; no source file is modified.

**Not supported:** FBX-to-FPL conversion; full FlatBuffers schema validation; vertex/mesh import into ARE; rendering; texture decoding; shader execution; fplbase Android runtime; animation/skin conversion; using texture lookup heuristics to silently select substitute textures. Real upstream FPLBase export fixtures and native CPU framebuffer/depth parity have not yet been checked. Inputs are bounded but should still be processed as untrusted files in an appropriate isolated offline environment.

FPLBase's old FBX converter documented a one-bone-per-vertex output constraint, despite the FlatBuffers schema describing four influences. This tool therefore does not reinterpret skinning data.

**Licensing:** FPLBase is Apache-2.0; ARE uses PolyForm Noncommercial. This integration copies no upstream source or schema content, uses source-format facts for compatibility, and does not change ARE's license or commercial permissions. Upstream reference: [`mesh.fbs`](https://github.com/google/fplbase/blob/4c9f5b751427f3be56a9277497b9078079aa1b9c/schemas/mesh.fbs), [`materials.fbs`](https://github.com/google/fplbase/blob/4c9f5b751427f3be56a9277497b9078079aa1b9c/schemas/materials.fbs).
