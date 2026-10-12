# Native original-model benchmark

This is an opt-in research executable, not a general glTF engine or a replacement
graphics driver. It extends the native work-room experiment with original indexed
meshes and skeletal animation. The public legacy wire still admits at most 64
triangles. Only the separate `AREMDL01` input selects bounded model admission.

## Execution and scope

`model_probe.py` verifies each supplied GLB's SHA-256 and parses an admitted subset
offline. It writes one typed input, then launches C++17. C++ samples the animation,
builds joint transforms, applies all exported weights, transforms/project vertices,
lights every original triangle, updates geometry, rasterizes, resolves 4x MSAA and
applies the existing FXAA operation. There is no Python callback in this loop.

Each work room carries a real stage operation and dependencies. The four existing
operation tags remain render, raster, MSAA and AA. Model preview colors identify
objects and diagnostic lighting; they do not visualize scheduler activity.

The admitted subset is one indexed triangle primitive and one mesh instance per
GLB, opaque double-sided geometry, optional one skin with four/eight/twelve
influences, affine static nodes, and STEP/LINEAR translation/rotation/scale clips.
The native process normalizes valid weight sums within 0.001 of one. Rotations use
normalized quaternions and shortest-arc interpolation. It clamps each animation
channel to its own key range. Every tested original triangle is submitted, without
sampling or LOD. Static models remain static. A multi-model scene combines chosen
clips and fixed placements; it has no gameplay, physics, attacks or hit detection.

The camera is orthographic and fitted once over the declared sampled timestamps.
Every instance is uniformly normalized from its default-pose bounds before the
declared placement transform. This is a visibility-controlled geometry benchmark,
not a perspective camera/frustum-clipping benchmark. Materials use per-face
diagnostic lighting. Embedded textures, PBR, transparency, shadows and original
normal maps are not evaluated. No graphics API or hardware GPU is submitted to.

## Comparison

Both timed paths use the same geometry and the same scalar sample/depth/resolve/AA
operations. The baseline uses the global four-stage Pipeline; the candidate uses
the four combined bio-inspired scheduling mechanisms from PR 39. The baseline
shares the explicitly expanded model admission. It is **not** a claim that the
historical 64-triangle executable could load these models.

Each case uses 256x256 pixels, 32-pixel tiles, four requested workers, three warmups
and 15 alternating baseline/candidate pairs. Every timed pair must match final
RGBA, pre-AA resolved RGBA and float32 depth exactly. The first frame additionally
matches a one-worker reference. Independent NumPy pose checks use a different
quaternion/vector and matrix-blending implementation. Wolfram supplies an exact
twelve-weight example, rather than performance estimates.

`total_ms` includes skinning, projection, triangle lighting, geometry validation
and copy, and the entire native render path. `geometry_ms` is the initial geometry
portion; `render_ms` is the remaining portion. Cold GLB load, typed input, camera
fit/construction, reference/warmups, parity comparisons, frame copies for output,
and serialization are excluded and identified separately. `cpu_ms` uses
`std::clock`; reported process CPU measurements here are from Linux. Windows C
runtime clock semantics must not be interpreted as equivalent process CPU usage.
This harness does not measure power, temperatures, present latency or game FPS.

Times from one shared host characterize these workloads, not arbitrary gaming
hardware. Paired ratios and raw observations are retained. Many sampled poses
change workload over time; the temporal sample distribution is not a confidence
interval from repeated identical frames.

## Reproduce

Keep the supplied original GLBs together in a local directory. The repository
contains only a checksum/metadata manifest, not the originals. With Python/NumPy
for offline preparation and a C++17 compiler installed:

```sh
python tools/benchmark_models.py --assets /path/to/originals --output-dir /path/to/evidence --phase all --repeats 15 --seconds 1800
python -m unittest software_gpu.tests.test_model_probe -v
```

The executable reads a bounded little-endian binary protocol, rejects invalid
counts, graphs, matrices, weights, indices, times and trailing bytes, and only
supports little-endian hosts. The model profile admits at most 6.1 million
vertices, 8 million triangles, 12 instances and 60 sampled times, plus independent
tile-reference/key/input-byte budgets. These are rejection limits, not memory
availability guarantees. Existing raster numeric contracts remain unchanged.

The benchmark records source and binary SHA-256, original-file hashes before and
after, typed-input hashes, response/frame hashes, raw timings and environment.
Original-model runs require the original assets; CI runs a tiny real generated
GLB, independent math checks and the actual native executable.

## Research connection

The glTF skin transform follows the official [Khronos skinning tutorial](https://github.com/KhronosGroup/glTF-Tutorials/blob/main/gltfTutorial/gltfTutorial_020_Skins.md):
global joint transform times inverse bind, with mesh-node transformation cancelling
in the resulting world-space skinned position.

[Pan 2025, arXiv:2505.06703](https://arxiv.org/abs/2505.06703) studies parallel
hierarchical skeletal updates on DirectX 12 / RTX 3080. This motivates a possible
future hierarchy scheduling experiment. Its GPU results are not transferred into
our CPU speedup numbers. The current bounded skeleton traversal is native CPU
code; no GPU hierarchy-scan algorithm is claimed implemented here.
