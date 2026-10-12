# Native render work rooms — experimental slice

Each point represents executable work with an address, owned output region,
dependencies and a completion state. Colour is an operation tag. Image RGBA is
separate. All pixel, sample, triangle and scheduling loops run in C++17.

| Operation / tag | Actual work | Required inputs | Owned output |
| --- | --- | --- | --- |
| Render / green | Perspective divide and screen-space triangle setup | Finite, already-clipped xyzw and flat RGBA | One prepared triangle |
| Raster / blue | Top-left coverage, 4 samples, strict depth test, flat shading | All prepared triangles | One tile's sample buffers |
| MSAA / orange | Four-sample integer colour average and minimum depth | Completed raster tile | One resolved tile |
| AA / purple | Existing engine's FXAA equations and neighbour reads | Resolved tile and one-pixel halo | One final tile |

The four address coordinates are `(slot_x, slot_y, operation, frame)`. This is
an explicit engineering interpretation of the requested four dimensions. Render
slots use `(primitive_index, 0)`; the other three planes use tile coordinates.
It does not assert four physical spatial axes or a four-valued truth calculus.

The wave is a dependency frontier. The current runtime uses four conservative
global barriers: each stage joins before the next starts. Within a stage, up to
eight native workers claim chunks of 32 rooms from an atomic cursor. Rooms move
through waiting, ready, running and done; they are logical work units rather
than one OS thread each. MSAA neighbours are complete before AA reads their
halos. Each tile has a single writer. Triangle submission order is preserved
inside each raster tile, including strict `<` depth and first-submission ties.

The final handoff opens only after every room completes. `to_framebuffer`
copies delivered colour/depth into the existing engine's `Framebuffer`. There
is currently **no hardware GPU API submission**, device upload or replacement
of the default rendering backend. A hardware GPU adapter is a separate task.

## Symbolic control and native boundary

`software_gpu/research/workrooms.wl` parses a held, finite DSL such as
`WorkRooms[32,32,8,0]`. It exports a fixed JSON descriptor. Unknown operations,
assignments in arguments and oversized plans are rejected. The actual Wolfram
evaluation is recorded in `evidence/workrooms-wolfram-v1.json`; its provider
reported undefined-global-symbol warnings but produced the descriptor, a
17-node/40-edge acyclic witness and all three successful rejection checks.

The sparse witness has fronts `[4,4,4,4,1]`: four primitives, four raster rooms,
four MSAA rooms, four AA rooms, one handoff. It encodes all primitive-to-raster
dependencies, each raster-to-resolve edge, neighbouring resolves-to-AA and
AA-to-handoff. The C++ barriers enforce a superset of these dependencies.
Production uses implicit tile addresses rather than a dense million-square
matrix or a Wolfram object for every room.

Python validates JSON, compiles, serializes requests and receives buffers. It
does not execute native work-room loops or appear in the compiled executable.
Wolfram is a control-plan and graph oracle; it is not required per frame.

Wire v1 is little-endian: `ARERIN01`, 32-byte correlation tag, five uint32 values
`width,height,tile,frame,triangle_count`, then 12 float32 clip coordinates and
four RGBA bytes per triangle. The response is `AREROUT1`, echoed tag, width and
height, resolved RGBA, final RGBA, float32 depth, uint32 JSON length and receipt.
The tag is a client-computed SHA-256 of the input payload and is **not native
authentication**. The boundary computes complete request/response/output
hashes. Build receipts bind the source files, flags and compiled binary.

Input bounds: dimensions 2..1024, tile size 1..64, frame 0..1,000,000,
1..64 triangles, width × height × triangles ≤ 67,108,864, workers 1..8,
repeats 1..30 and a 180-second subprocess timeout. Invalid/truncated/trailing
wire input, nonfinite coordinates and geometry outside the clip volume reject
the entire request before any framebuffer handoff. This slice accepts flat
colour and already-clipped geometry; it does not implement arbitrary shaders,
textures, clipping or alpha blending. RGBA alpha is stored, not blended.

## OpenProblems and cellular-computation connection

The inspected upstream is **v1.0.0**, commit
`f54e8e985e1391807c60741dbee99c85762fbd45` of
[openproblems-bio/openproblems](https://github.com/openproblems-bio/openproblems/tree/v1.0.0).
Its [docker directory](https://github.com/openproblems-bio/openproblems/tree/v1.0.0/docker)
provides environments for datasets, methods and metrics; it is not a rendering
core. The directly inspected
[diffusion-map implementation](https://github.com/openproblems-bio/openproblems/blob/v1.0.0/openproblems/tasks/dimensionality_reduction/methods/diffusion_map.py)
constructs a normalized graph Laplacian `I - D^(-1/2) A D^(-1/2)` and an
eigenvector embedding of an expression-data neighbour graph.

The transfer in this slice is structural: explicit graph neighbours, sparse
dependency representation, separated method/oracle/metric and reproducible
inputs. A directed task-dependency matrix and a normalized biological affinity
matrix serve different purposes. No OpenProblems package, biological dataset,
UMAP/PCA/eigensolver, diffusion equation or biological simulation has been
ported or benchmarked here. No upstream algorithm source was copied. Per-file
licenses would need review before any future code reuse.

The cellular analogy is useful for local state and communication: a room has
inputs, work and outputs. The scheduler is a staged dataflow system, not a
living cell or a demonstrated self-organizing cellular automaton.
[Learning Graph Cellular Automata](https://arxiv.org/abs/2110.14237) and
[Cellular automata, many-valued logic, and deep neural networks](https://arxiv.org/abs/2404.05259)
are research context, not speed or biological-validation evidence for this code.

Tavily and Connhex calls during this investigation were blocked by their app
connections; no search results or temperature measurements from them are
claimed. Wolfram evaluation and local source/runtime checks did work.

## Reproduce

Use a repository checkout, a C++17 compiler with threads and the project's
NumPy dependency. Native sources are not packaged in the existing wheel.

```sh
python -m unittest software_gpu.tests.test_workrooms -v
python tools/benchmark_workrooms.py --output-dir /tmp/workrooms --repeats 15
```

The benchmark creates a standalone executable, build receipt, complete raw
timing receipt and `render.ppm`. Python only launches the process; all repeated
native frames and their worker comparisons execute inside C++.

## Initial measured result

At 640×640 with four submitted triangles, tile size 1 executes **1,228,804**
work rooms: 4 setup + 409,600 raster + 409,600 MSAA + 409,600 AA. The handoff is
one additional control node. Rasterization performed 1,547,093 passing sample
writes per frame, including overdraw. These are real render operations, not
counts of coloured display points.

| Room size | Workers | Rooms/frame | Median frame ms | Median process CPU ms/frame |
| --- | ---: | ---: | ---: | ---: |
| 1×1 | 1 | 1,228,804 | 62.949 | 62.593 |
| 1×1 | 4 | 1,228,804 | 36.880 | 128.318 |
| 16×16 | 1 | 4,804 | 37.659 | 37.663 |
| 16×16 | 4 | 4,804 | 12.611 | 33.671 |

Fifteen measured frames per case follow one warmup. Native frame timing
includes scheduler setup, worker creation/join and completion scanning;
excludes process startup, input parsing, initial allocations, parity comparison
and output serialization. Four-vs-one-worker ratios are 1.71× and 2.99×, from
separate process batches on one host, not statistical guarantees. Small rooms
increase scheduling cost and CPU time; millions of rooms are feasible but
are not automatically the efficient granularity. C++ does not guarantee a
cool CPU. No temperature sensor was available and no thermal claim is made.

All three full output buffers match across worker and tile choices. Final RGBA
SHA-256: `ba0ace0583f04bc150116ef8948483a62d7ae70de7a39b1fb605d3f253d57874`.
Independent small-scene tests compare every resolved/final RGBA byte and depth
bit against the existing `MSAARasterizer`/`FXAAPass`: shared edges, strict depth
ties, alpha, random varying depths/w, backfaces, degenerates, uneven tile
borders and invalid input. The large benchmark proves native parity and room
scale; it is not an independent full-resolution Python rerender.

Raw results: `evidence/native-workrooms-v1.json`. Full canonical CI on the exact
reviewed head is required before integration. This is an optional research
implementation and makes no CPU-to-hardware-GPU performance claim.

Local verification: 230 executable tests passed, overall Python line coverage
68.7%, all 16 existing floors passed, new Python boundary 98.5%. The unmodified
231-test suite is host-blocked by `AF_UNIX` socket creation (`EPERM`), which also
fails its nested coverage run. The host-only rerun omits exactly that existing
socket test; no repository tests or floors were changed. Native ASan/UBSan
passed actual 640×640 frames and invalid-wire cases. Leak checking was not
available; Python coverage is not C++ coverage.

`native-workrooms-validation-v1.json` and compressed logs preserve that distinction.
The separately executed 256px/15-repeat/eight-mode existing-backend benchmark
passed framebuffer parity, checkout-source audit and analysis; it is a
regression control, not a comparison with this new restricted native renderer.
Its original JSON is stored as `workrooms-existing-backends-v1.json.gz`;
decompress it before using the workbench's `audit`/`analyze` commands.
`workrooms-measurement-context-v1.json` records the AMD EPYC 9V74 host,
nine available logical CPUs, thread environment and native IQR/MAD statistics.

The first Windows 3.12 CI run found a pre-existing symbolic microbenchmark
test requiring positive time for only four tiny native frames. Its test batch
now contains 2,000 real frames/sample; the 15-sample, positive-duration,
counter and bit-parity assertions remain. No timer values are clamped or
fabricated and no native renderer code changed in this correction. The nine
symbolic native regressions pass locally after the correction; final-head CI
is the cross-platform gate.
