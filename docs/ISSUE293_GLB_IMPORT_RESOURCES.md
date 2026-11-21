# Issue #293: GLB Import resource-cost investigation (offline)

This is an evidence-bound **copy-elimination slice**, not a new GLB/FBX importer,
exporter, model streaming system, or automatic cache admission policy.

## Existing authorities and actual admission

- `tools/glb_container_preflight.py`: validates GLB2 framing/metadata, previously
  copied the entire BIN chunk to parse its declared size. It now retains a
  `memoryview` only while the original input is alive. The JSON chunk is still
  decoded into Python bytes for the existing strict parser.
- `software_gpu/research/model_probe.py`: independently enforces SHA-pinned
  input bytes and bounded typed accessors for the existing AREMDL03 importer.
  **Only one mesh and one indexed triangle primitive** are admitted by that
  importer; 100/1300/3500-mesh inputs are positive *container* tests and
  explicit negative *native-import admission* tests.
- `software_gpu/graphics/preparation_cache.py`: separate renderer-local
  pure vertex preparation cache; no new caching or visibility owner.
- `software_gpu/research/model_material_import.py`: bounded images, no external
  image URLs. Native C++17 models retain their current wire format.
- No authoritative ARE FBX export path was found in the inspected repository;
  Assimp upstream export performance must not be cited as ARE speedup.

## Measured preflight copy — before/after and scope

The old parser used `data[pos:pos+size]` in the chunk loop, allocating an
unnecessary BIN duplicate. The revised parser uses
`memoryview(data)[pos:pos+size]`; its output dictionary, framing validation,
JSON decoding, BIN-length checks and errors remain unchanged. This is a
**linear extra-copy reduction**, not a confirmed quadratic-growth fix.
Therefore the issue's geometric growth formula and allocator-ownership-transfer
changes are **not** introduced into unrelated code.

The new isolated workflow runs real code against genuine GLB2-structured bytes
created deterministically by a checked-in fixture generator: 1/100/1300/3500
meshes, several accessor indices/materials, SHA-256 per input, 4 MiB BIN.
The geometry is **synthetic test geometry**, not independent third-party or
private Owner assets. It runs 15 paired interleaved preflight A/B repeats on the
same machine, recording each timing and peak traced Python allocation with
median, p95, IQR, MAD and CPU/affinity/source SHA. Artifacts remain attached
to the exact Actions run, not promoted into historical *full-frame* rankings.

The bounded negative regression verifies source length, invalid byte length,
accessor count/stride/alignment/ranges, broken headers, fail/reimport after
errors, and 100 large-to-small import/release attempts; each operation uses real
GLB2 bytes, and no released Python parse objects may remain unexpectedly held.
A separate true 64x64 CPU draw verifies RGBA8 and Float32 depth byte digests
for the admitted one-mesh file across two runs. Multi-mesh **native draw**
parity is unsupported, not simulated.

### Stage matrix

| Stage | Current evidence boundary |
| --- | --- |
| File read, I/O/cache | Native `read_glb` reads and SHA checks actual files; no independent cold-cache claim |
| JSON/BIN framing | 15-pair `inspect_glb` A/B and peak allocation measurement |
| BufferViews/accessors | Real NumPy accessor decode, invalid range/stride/count/alignment negatives |
| Typed native import | One-mesh accepted; other mesh counts fail closed |
| First and following draw | One admitted 64x64 CPU raster replay with RGBA8 and Float32 depth |
| Release | 100 large/small cycles with bounded traced memory, separate from OS RSS |
| OS peak RSS | Not independently isolated per stage; no invented per-stage RSS ranking |
| Export | No ARE GLB/FBX export path measured; upstream Assimp work is only a reference |

No Vulkan/DirectX/GPU, Android, Aurion gameplay, throughput or FPS claims.
The existing 64x64 wave, Top-left, Float32 and strict-depth contracts stay as-is.
Changes are covered by full exact-head Linux/Windows CPU/LLVM CI. Native
PBR parity and independent original multi-mesh assets remain separate gates.

## Reproduction

```bash
python -m unittest software_gpu.tests.test_glb_import_resource software_gpu.tests.test_glb_container_preflight -v
python -m software_gpu.benchmarks.benchmark_glb_resources --output evidence/issue293-ci/glb-preflight-measurements.json --bin-bytes 4194304
```
