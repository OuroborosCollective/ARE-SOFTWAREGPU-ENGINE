# KTX2/BasisU: fail-closed opt-in Khronos transcoder and bounded mip admission

Issue [#283](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/issues/283).
This is **offline authoring**, not a change to native raster, C++17 PBR material math,
sRGB sampling, texture filtering, gameplay authority, or any live endpoint.
The existing PNG/JPEG glTF importer remains the **single render authority**.

## Khronos transcoder

Use upstream **Khronos KTX-Software 4.4.2** `ktx validate --gltf-basisu`
and `ktx extract --transcode rgba8 --level 0`. Obtain binaries from the
[Khronos v4.4.2 release](https://github.com/KhronosGroup/KTX-Software/releases/tag/v4.4.2)
in compliance with its license; this repository does **not** vendor a binary.

Linux x86-64 official `tar.bz2` SHA-256:
`a8781bad05f9624edbf910b7f258cd0a4ba7d3e63b49ecc0a0ab440bf6a0a245`.
The pinned `ktx` executable SHA-256 within that archive is
`2028e023a18e827e66362a9e184052f40192566b10f92655a337e2eb8ea0829b`.
An unverified or missing binary does not silently fall back to a custom decoder.
The input binary, original GLB, referenced images, and text license proof must
have matching SHA-256 values before conversion begins.

## Manifest and run

```json
{
  "source_glb": "/private/original-basis.glb",
  "source_sha256": "<64-hex-real-source-hash>",
  "source_bytes": 12345,
  "lod": "lod0",
  "images": [{
    "image_index": 3,
    "sha256": "<64-hex-original-ktx2-hash>",
    "license": "CC0-1.0",
    "license_path": "/private/license.txt",
    "license_sha256": "<64-hex-license-file-hash>"
  }],
  "transcoder": {
    "path": "/private/verified-ktx/bin/ktx",
    "sha256": "2028e023a18e827e66362a9e184052f40192566b10f92655a337e2eb8ea0829b",
    "version": "4.4.2"
  },
  "budget": {
    "max_dimension": 4096,
    "max_pixels": 16777216,
    "max_texture_bytes": 41943040,
    "max_lod_bytes": 134217728,
    "max_mip_bytes": 67108864
  }
}
```

Substitute real file size, source hashes, and image index from the private
original. All source paths must be local and absolute; HTTP/file/data URI
fetches and external glTF image/buffer resolution are forbidden.

```sh
python -m tools.ktx2_texture_admission /private/manifest.json \
  --output-dir /private/new-converted-output
python -m unittest software_gpu.tests.test_ktx2_texture_admission -v
```

The output directory must not exist. It is published only after validation,
real Khronos transcode, output dimensions and PNG integrity checks succeed.
It contains `converted.glb` (embedded PNG in standard glTF 2.0) and `receipt.json`.
No original GLB is uploaded. Original encoded KTX bytes are retained in the
private converted payload; do **not** commit owner GLBs or private manifests.

## Mip budgets and truth boundaries

- Only embedded 2D ETC1S BasisLZ and LDR UASTC with supported supercompression,
  an opaque material subset, matching sRGB/linear usage, and base mip level 0.
- Reject malformed headers/DFD/KVD, nonconformant DFD primaries/transfer, indexes/ranges, overlapping mips, unsupported
  compression/URI types, color-space ambiguity, non-finite material metadata,
  oversized decoded surfaces and combined LOD residency.
- Per-texture max dimensions, pixels, base decoded bytes, each mip, entire
  mip-chain estimate, and per-LOD summed resident bytes are explicit.
  Higher mips are **not loaded**; eviction/streaming is **not implemented**.
- The receipt has original GLB SHA, per-image SHA, license and license-evidence
  SHA, conversion version/binary SHA, decoded RGBA SHA, PNG SHA and rewritten
  GLB SHA. No lossy-compression framebuffer-byte parity is promised.
- Existing native PBR visual correctness is verified using real C++17
  Beauty/Float32 depth and fixed camera in the separate Khronos CI job.
  The standalone conversion receipt deliberately says `not_measured` for image
  and depth differences: only an actual subsequent render establishes them.
- This is **not** a native 15-paired quality-matched benchmark. Until quality
  comparability is specified, no speed ranking or gameplay FPS claim is made.

## Local learned weights: execution coverage requirement

`software_gpu/tests/test_learning_route_coverage.py` enumerates the six
public `SoftwareRasterizer` backends and invokes each against real raster data
with a real SQLite store. It compares complete RGBA8 and Float32 buffers with
learning disabled and checks new persisted samples/weights. A controlled test
weight snapshot drives the safe `tiles` candidate and a blocked flag restores
the reference while hashes remain equal. Synthetic test weight values establish
**routing behavior**, not performance gains. Real calibration uses complete
paired renders as covered in `test_local_learning.py`.

Both `.mp4` H.264 and `.mkv` FFV1 exports use the existing `encode_frames`
learner with decoded-frame parity. The same test module inventories 12 distinct
render, raster, and output entrypoints, distinguishing active learning,
delegated weight usage, byte serialization and unweighted external/native paths.
New entrypoints must be reviewed instead of silently claiming universal coverage. BMP/PPM only serialize previously rendered
pixels: they are **not separately optimized**, and it would be false to claim
these byte writers or the external Blender engine select learned kernels.
Native C++17 PBR model probe and KTX conversion are still unweighted offline
production paths. Their absence is documented; no green test may claim
universal learn-weight path selection.

## Project surface classification

- **Production/Core:** unchanged; opt-in offline converter only.
- **Test:** true Khronos-encoded KTX2/PBR/Depth integration plus malformed
  input cases; real raster and FFmpeg learning integration.
- **Persistence:** original SHA and licenses in private receipt; SQLite
  learning DB remains local and outside deterministic authority.
- **Effects:** native Beauty, Float32 Depth and source-derived diagnostics;
  shader semantics unchanged.
- **Runtime projection:** no server/APK/live deployment proof from this feature.
