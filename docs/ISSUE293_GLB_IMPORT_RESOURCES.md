# Issue #293 – GLB2 Buffer Ownership and CPU Import Evidence

## Ownership inventory and non-negotiable GLB2 boundary

- `tools/glb_container_preflight.py` remains byte-identical to `main`'s
  GLB2/Khronos sandbox pin from Issue #284; its historical BIN-copying
  behavior is measured but **not changed**. Altering it directly triggers the
  independent sandbox source SHA invariant and is not authorized by this change.
- `software_gpu/integrations/aurion/offline_lod_worker.py` is the actual
  optimizable owner here. Its `_load_glb()` formerly sliced an entire BIN
  buffer from already-read source bytes. It now uses `memoryview(data)` and
  decodes the small bounded JSON chunk separately. Accessors always produce
  owned NumPy copies before the local input view is released.
- `software_gpu/research/model_probe.py` already uses memoryviews for its
  checked SHA-pinned native AREMDL03 input and **only accepts one mesh and one
  indexed primitive**. The 100/1300/3500 mesh test files are valid GLB2 container
  inputs but remain **unsupported** as native AREMDL03 assets.
- `tools/glb_diagnostic_evidence.py` has its own bounded topology diagnostics.
  `software_gpu/graphics/preparation_cache.py` owns only pure vertex
  preparation: no texture/visibility cache authority, no auto activation.
- No ARE GLB/FBX export owner was found on this revision. Assimp upstream
  exporter measurements are separate reference data, not ARE performance.

## Measured change and limits

Actual RED test: GitHub Actions run 44956606939 on
`de8f7341ee11e42e2415e2c782cba8dd421fce24`:
`WORLD_FORGE_DUPLICATED_GLB_BIN`, 8,408,479 traced peak bytes for a
4 MiB-bin valid GLB, exceeding 7 MiB. Fix removes the **linear** extra copy
from the LOD import path; there is no proven quadratic capacity growth.
Therefore no `capacity + max(4096,capacity//2)` allocator patch is made.
The canonical GLB2 parser and native renderer contracts remain unchanged.

Generated test GLB2 data contain real structurally valid bytes and SHA256
source digests for **1/100/1300/3500 meshes**, varying accessor indices,
primitive materials and BIN sizes. These are **synthetic test assets** and
must never be labelled independent Owner or Khronos samples.

The isolated 15-pair interleaved benchmark is intentionally **only a
byte-slicing expression A/B** (`bytes` copy versus `memoryview` slice),
not a full model importer throughput or an ARE FPS benchmark. It records 15
raw timings, peak traced allocation bytes, median, p95, IQR, MAD,
paired ratios and exact source/fixture hashes. These results do **not** enter
the historical full-frame CPU speed leaderboard.

A second profiler invokes the actual existing single-mesh path, in separate
15-run stages: file read and SHA, GLB2 JSON/BIN framing, SHA-pinned native
`read_glb`, real typed accessor decoding, typed import, first CPU draw,
follow-up CPU draw, and GC release. It reports independent stage wall times,
traced Python allocation peaks, NumPy/Python/CPU/affinity, process cumulative
VmRSS/VmHWM and exact RGBA8 and Float32 depth digests. Cache is
**uncontrolled warm OS page cache**, and process high-water RSS is not falsely
attributed to individual stages; repeated independent passes are **not an
additive full end-to-end pipeline duration**.

Unit tests additionally exercise 100 large→small load/reject/reimport cycles,
truncated BIN, invalid declared byteLength, invalid counts, stride,
alignment, corrupt accessor refs and failed-to-valid reimport. WorldForge
arrays must stay valid after source release; unsupported inputs fail closed.
The admitted one-mesh 64×64 CPU draw is tested for exact RGBA8/Float32-depth
replay. Native multi-mesh PBR parity and independent original asset
benchmarks remain **UNVERIFIED**, not simulated.

## Proof and reproduction

```bash
python -m unittest software_gpu.tests.test_glb_import_resource software_gpu.tests.test_aurion_offline_lod -v
python -m software_gpu.benchmarks.benchmark_glb_resources --output evidence/issue293-ci/bin-slice.json --bin-bytes 4194304
python -m software_gpu.benchmarks.profile_glb_import_stages --output evidence/issue293-ci/one-mesh-stages.json --repeats 15
```

Gate: exact final GitHub PR-head Linux/Windows/LLVM/native CI and
separate measured-job receipt SHA audit, then append-only `Memory.md`
checkpoint and merge readback. No automated training, PBR/OS cache-policy
change, Vulkan/DirectX, Android runtime or gameplay-FPS admission.
