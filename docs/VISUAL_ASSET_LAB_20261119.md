# Visual Asset Lab – opt-in GLB diagnostics and newest-first test catalog

**Design scope, 2026-11-19.** A separate source-derived diagnostic pilot, not a replacement for the native AREMDL03 PBR/GLB renderer, the authoritative game simulation, the APK or the historical CPU rankings.

## Actual implemented pilot

- `python -m tools.visual_asset_lab /private/verified.glb --output-dir /tmp/are-visual-asset`
- `python -m tools.visual_asset_lab /private/verified.glb --output-dir /tmp/are-visual-asset --max-triangles 2000`
- Outputs: SVG geometry wireframe, optional SVG UV projection, SHA-256-pinned JSON receipt. They are computed from real embedded glTF2 indexed float32 positions and UV coordinates.
- The SVGs are **structural projections, not PBR beauty frames**. They are not texture sampling, GLB animation, material evidence, depth parity or native frame timings. PBR `not_executed`, speed `not_measured`, quality verdict `not_assessed`.
- The existing `tools.glb_diagnostic_evidence` supplies independent topology/UV/material *diagnostic statuses*. External texture URIs are never opened or fetched. No server/HTTP endpoints or public uploads are added.
- Current opt-in visualization accepts exactly one supported indexed triangle primitive with no more than 5000 triangles, bounded source size, and supported embedded buffer layouts. A 2M-triangle original does **not** silently pass this pilot; use verified, smaller LOD assets or a future bounded streaming/decimation slice.
- Output destination must be a fresh empty directory, avoiding accidental reuse of stale image artifacts. Test fixtures use real in-memory GLB2 BIN chunks; that is test evidence, not owner-original runtime evidence.

## New tests first

Canonical source: `evidence/test-series-catalog-v1.json`; generator: `software_gpu/benchmarks/test_series_catalog.py`.

`python -m unittest software_gpu.tests.test_visual_asset_lab software_gpu.tests.test_test_series_catalog -v`

The documentation builder `software_gpu.benchmarks.spherepop_rankings.render` prepends newly registered tests before archived timing tables, ordered by *descending* ISO date, with stable test-ID tiebreak. The historical WAVE/IMPACT receipts and number formatting remain unchanged. The **registered** status is not proof of full CI; a future performance rank requires canonical full-frame timing, source/build/runner SHA, at least 15 paired real runs, RGBA8 and Float32 depth parity plus a separate verification readback.

The private ARE workbench and public leaderboard site are **not** automatically deployed by this repository change; the current MCP ranking has a pinned historic snapshot with `legacy-git-blob-pinned-self-digest-mismatch`. Website sync needs a separate original-receipt/readback gate.

## Follow-on integration sequence (not yet implemented)

1. **Native owner LOD admission** – issue #103: original-asset SHA, exact 30k/12k/4k variants, real AREMDL03 PBR frames, original vs LOD visual QA, 15 paired end-to-end timings, raw RGBA/depth and peak RSS. Do not pass an external Mesa ratio off as native.
2. **KTX2/BasisU opt-in texture pipeline** – deterministic texture conversion and bounded transcode with material/UV parity, legal license and sRGB/linear handling.
3. **glTF 2.1 compatibility** – extension-aware feature-gated parsing only after ratification; v2.0 remains the unaffected reference. No unsafe 64-bit GLB guessing.
4. **Transparency/shadows** – explicit alpha-test, blend order/depth write, shadow-map numerical semantics and full-frame golden tests; default opaque path untouched.
5. **Adaptive cost model** – offline training/selection from equivalent-color/depth paired CPU evidence. Selected policy read-only and reversible; no clock/random in the render decision or Aurion 100ms authority.
6. **Pixel forensics** – opt-in trace of source primitive, depth winner, fragment calls and draw order with receipt digest; no hidden output/buffer mutation.
7. **Android owner UDS** – issue #235 remains separately gated by real multi-UID/SELinux device evidence. A source-only CI test is not Android runtime acceptance.

## Project surfaces

- **Production:** none changed; opt-in offline inspection only
- **Test:** new real-GLB fixtures, negative input gates and newest-first catalog regression
- **Persistence:** local SVG/JSON artifacts and source-controlled catalog; no gameplay save-state authority
- **Effects:** deterministic SVG wireframe and UV projections (not native PBR)
- **Core:** native C++17, Python rasterization and 10Hz game tick unchanged
- **Runtime projection:** no deployed Gradio/API/Android verification claimed

**Merge gate:** exact final-head CPU/LLVM/Mesa/Gradio CI and baseline regression, append-only single `Memory.md` change + evidence, independent GitHub readback. No unmeasured FPS claim.
