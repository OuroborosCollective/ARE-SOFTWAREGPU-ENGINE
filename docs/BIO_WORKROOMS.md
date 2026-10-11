# Four biological architecture principles in an exact native renderer

This optional C++17 experiment combines spatial indexing, resident workers,
local dependency frontiers and generation checkpoints. Each point remains an
actual addressed work room. The four coordinates are tile/primitive x, y,
operation and frame; colour labels the operation. All rendering, scheduling,
comparison and repeated timing run inside a standalone native executable.
Python builds and transports the binary request/response. Wolfram verifies a
small dependency model and supplies the existing fixed work-room descriptor.

| Research inspiration | Actual transfer | Deliberate limit |
| --- | --- | --- |
| [BioDynaMo](https://arxiv.org/abs/2301.06984) | Conservative tile/triangle CSR index; cached bounds and inverse area rebuilt each frame; stable primitive order | No NUMA placement, Morton sorting, biological agents or skipped render outputs |
| [PhysiCell optimization](https://arxiv.org/abs/2306.11544) | Reuse sleeping C++ workers, arrays and receipts between waves/frames | No approximate time steps or reuse of stale geometry/results |
| [Min protein waves](https://doi.org/10.7554/eLife.03949) | Raster completion releases own MSAA; each resolve publishes to nearby AA rooms | A dependency wave, not a reaction-diffusion simulation |
| [Reactome cell-cycle checkpoints](https://reactome.org/content/detail/R-HSA-69481) | Frame-generation tickets, atomic claim/completion transitions, explicit predecessor checks and sealed handoff | A scheduling contract, not a biological cell-cycle model |

The principles are engineering interpretations. The upstream authors' speedups
do not describe this renderer. No biological simulation code or dataset was
copied. The original [OpenProblems v1.0.0 docker directory](https://github.com/openproblems-bio/openproblems/tree/v1.0.0/docker)
provides research environments; its transferable contribution is separation of
methods, fixed inputs and metrics. It does not implement a GPU kernel.

## Local waves and the ownership contract

Each raster room writes only its own four-sample tile. MSAA then resolves that
tile. AA reads a one-pixel halo, including diagonals: up to **nine** resolved
tiles, including its own. Every resolved predecessor decrements its successors'
pending counts with an acquire/release atomic RMW. Only the worker observing
the transition from one to zero executes that AA room. This carries all
predecessor writes to the final reader; completion order is free, pixel and
sample arithmetic are unchanged. A stage join occurs before the final handoff.

The combined scheduler has a primitive-setup barrier, then a local
raster/resolve/AA frontier. It does not allocate a million-square adjacency
matrix or an OS thread for every point. Triangle bins use sparse offsets and
16-bit indices and preserve ascending submission order. Shared scalar sample
operations preserve top-left coverage, ordered float32 arithmetic, strict `<`
depth and first-submission ties. Fast math and FP contraction remain disabled.

Checkpoint tickets belong to one frame generation and one room. Duplicate or
stale claims, incomplete predecessors, premature completion and incomplete
handoff reject. Checkpoint storage and native worker objects are allocated once;
no worker busy-waits between frames. A failed frame never exposes a framebuffer.
One caller owns a pipeline; concurrent external calls on the same pipeline are
unsupported. A pipeline's admitted scene is immutable, while every execute
recomputes all render work and bins.

The baseline mode retains the four global waves. The four single-feature
modes, the combined mode and four leave-one-out modes allow observation of
interactions. They are fixed before measurement; no adaptive tuning or
performance-based removal of checks occurs in this experiment.

## Reproduce and admit results

From a source checkout with NumPy and a C++17 compiler:

```sh
python -m unittest software_gpu.tests.test_bio_workrooms software_gpu.tests.test_workrooms -v
python tools/benchmark_bio_workrooms.py --output-dir /tmp/bio-workrooms --repeats 15 --max-seconds 600
```

The build includes a byte-exact historical test fixture from commit
`87ff610cd9419dd4b465e60bc19eb367a6b1a8f2`; SHA-256 is
`8645f2f2bc824107ecf9f7e80c155b84622f099c0aacb0c4870d580ba91b48ca`.
It also admits the unchanged historical `core.hpp` hash. The fixture makes the
old/new comparison reproducible in shallow CI checkouts. It is an independent
frozen oracle, not a second production implementation to maintain or activate.
Input/response IO and the current scalar sample kernel are shared.
Git attributes keep the admitted headers at LF even with `core.autocrlf=true`;
a CRLF checkout failure was reproduced before applying these narrow rules.

Each case uses the same input bytes, worker count and compiler flags for both
renderers. Three untimed warmups precede 15 baseline/candidate pairs; their
order alternates. Every timed output is checked byte-for-byte for resolved and
final RGBA and bit-for-bit for depth against the frozen single-worker renderer.
Timing excludes this comparison. Two seeded scene families exercise large
overlapping triangles and 64 sparse triangles; independent small-resolution
tests use the existing Python MSAA/FXAA renderer, not another copy of the new
scheduler. The full native benchmark is 640×640; it does not use the Python
oracle for a full-resolution rerender.

Frame elapsed time includes all rendering, bin rebuilding, scheduling,
synchronization and final readiness/epoch scanning. It excludes startup,
parsing, initial allocation/resident-worker creation, parity checking,
serialization and Python transport. Constructor times and full process-batch
elapsed time are separately recorded. The reported factor is the ratio of
frame medians; paired ratios, IQR, MAD and raw samples are also preserved.
Overlapping frontier stage times describe one shared interval and must not be
added. CPU time is separately measured; neither metric measures energy.

The benchmark contains a baseline/refactored-baseline control. Its spread helps
identify host noise and the scalar/IO refactor's effect; it does not guarantee
that a small observed difference is causal. Source and binary hashes bind each
receipt. Exact current-source audit must precede any reuse of the numbers.

## Validation and limits

`bio_workrooms.wl` constructs a 41-node/142-edge model. Actual Wolfram evaluation
confirms an acyclic graph, pixel-read-equivalent Moore halos and one AA release
after all required resolves for 100 seeded resolve orders. This finite model is
not a C++ memory-model proof or performance measurement. The C++ acquire/release
implementation is separately exercised by threaded oracles and ThreadSanitizer.

Tests include uneven room sizes, one-pixel rooms, shared edges, depth ties,
varying clip w/depth, alpha, backfaces, degenerates, all ten modes, repeated
generations, corrupt/truncated wire, unknown policies, compromised baseline/core
fixtures, a real compiler failure and worker exception recovery. Native ASan,
UBSan and ThreadSanitizer runs supplement the tests. Python line coverage does
not measure C++ branches; the repository does not set a C++ coverage floor.

The existing bounds remain: 2..1024 pixels/axis, 1..64 pixels/room side,
1..64 triangles, pixels×triangles ≤67,108,864, workers 1..8 and at most 30
repeated pairs/request. Each resolve/AA tile has one writer. Checkpoints on
millions of rooms can be expensive because of per-room atomic transitions,
neighbor checks and a shared completion counter. Choosing 16×16 rooms reduces
control work without changing pixel outputs. It does not create additional
physical execution units.

This is an optional CPU software renderer with already-clipped finite geometry,
flat triangle colours, 4x MSAA and existing FXAA. It does not implement arbitrary
game shaders, textures, blending or a graphics-driver interface. The final node
returns CPU buffers usable by `to_framebuffer`; it submits no hardware GPU work.
There are no GPU-parity, game-FPS, temperature or energy claims. C++ and worker
limits do not guarantee a cool CPU. Quicknode RPC would supply blockchain data,
not render-core timing, and is not part of the measurements. The Game Development
Studio CLI is unavailable here; its comparison discipline is applied to the
real native harness, without claiming a sealed game-dev capture.

Results and exact local/canonical verification receipts are recorded in
`evidence/bio-workrooms-*.json` and the associated compressed logs. Leave the
optional module unused or revert this isolated experiment for rollback. The
existing default rendering backend is not activated by this module.
