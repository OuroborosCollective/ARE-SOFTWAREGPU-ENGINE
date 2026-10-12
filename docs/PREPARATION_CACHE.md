# Opt-in preparation-cache experiment

The cache reuses pure vertex setup, clipping/screen mapping, triangle assembly
and ordered tile candidates. Every draw still performs coverage, current-depth
tests, varying interpolation and fragment shading. No visibility or framebuffer
result is cached. This is a CPU experiment, not a hardware-GPU comparison.

```python
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.surface_plan import BATCH_FIRST_POLICY

fb = Framebuffer(256, 256)
renderer = SoftwareRasterizer(
    fb, num_threads=1, backend="tiles-plan", plan_policy=BATCH_FIRST_POLICY,
    preparation_cache_bytes=32 << 20, preparation_cache_entries=8,
)
try:
    fb.clear(depth=1.0)
    renderer.draw_mesh(vertices, indices, shader)
    print(renderer.last_preparation_receipt)
    # Reuse setup with unchanged inputs; redraw all coverage/depth/fragments.
    fb.clear(depth=1.0)
    renderer.draw_mesh(vertices, indices, shader)
finally:
    renderer.executor.shutdown(wait=True)
```

The default is `preparation_cache_bytes=0`, so existing callers do not retain
entries. Supported backends are `tiles` and `tiles-plan`. The cache is owned by
one renderer; concurrent draws into a single renderer/framebuffer are not
supported. Inputs and uniforms must not change during a draw, as on the original
renderer. `renderer.preparation_cache.clear()` explicitly releases retained data.

## Dependencies and bypass

Only the known `VertexColorShader.vertex_shader` and
`BlinnPhongShader.vertex_shader` function identities are admitted. A subclass
that overrides vertex execution and unknown/stateful vertex shaders run the
ordinary path. Arbitrary fragment functions may run: they are never skipped or
cached. This admission covers known pure vertex functions only, not arbitrary
shader proof or inference.

Every draw hashes relevant input contents, dtype, shape and strides. Cache
correctness does not rely on caller version counters or object identity.

| Input change | Preparation behavior |
| --- | --- |
| Position, indices, submission order, viewport dimensions, tile size | New key; full draw preparation runs again. |
| Vertex color | New key for both admitted vertex functions. |
| Normal/UV, MVP or normal matrix | New key for Blinn-Phong; these are not dependencies of the vertex-color function. |
| Scan threshold | New key; pre-execution pair features depend on it. |
| Batch threshold or draw fallback threshold | Existing bins can be reused; these decisions and receipts are recomputed. |
| Fragment-only light/material/texture state | Setup may hit; current fragment function/state executes again. |
| Current framebuffer/depth | Setup may hit; current coverage/depth executes again. |
| Input iterator, unsupported container/array, unknown vertex function | Bypass; do not consume an iterator while constructing a key. |
| Entry exceeds retention budget | Bypass retention; execute the real draw. |

The first slice invalidates the **whole draw** even for one changed vertex. It
has no event queue, per-object dependency graph, partial update algorithm,
inference-wave culling or inter-frame framebuffer reuse. A camera move can
invalidate nearly everything. Clearing and replaying draws remains the caller's
responsibility; preserving existing depth retains the strict-less first-draw
tie rule. Removing foreground geometry requires an ordinary cleared/full redraw
to reveal the background.

Retained coordinate and varying arrays are detached from caller arrays and
backed by immutable bytes; attribute maps and candidate lists are immutable.
Candidate order and float operation order are preserved. Tile bins are bound to
the prepared triangle object, viewport, tile size and scan threshold. A mismatched
bundle fails before raster writes. Invalid mesh indices still raise through the
original preparation path.

## Retention and receipt

The LRU has explicit entry and accounted-byte limits. Accounting covers retained
containers, array owners and an LRU-record allowance, with shared owners counted
once per entry. It is not an RSS or transient-allocation guarantee; a miss may
allocate setup/copy buffers before its entry is rejected. Python allocator and
native library overhead can exceed the accounting figure.

`last_preparation_receipt` is `None` when disabled. When enabled, it records
`hit`, `miss` or `bypass`, reason, input key, retained bytes/entries, evictions,
triangle/tile counts and key/setup milliseconds. Timings are observations and
are excluded from `last_plan_receipt` and its deterministic digest. Both receipts
are derived render diagnostics, not gameplay authority.

## Reproducible CPU measurement

```bash
python -m software_gpu.benchmarks.compare_preparation_cache \
  --output-dir evidence-out --pixels 256 --workers 1 --repeats 15 \
  --cache-mib 32 --max-seconds 900
```

Five seeded scenes and three scenarios (`static`, `one-vertex`, `all-vertices`)
compare three rotated/interleaved modes: uncached, warm cache and cleared cold
cache. Each case has one warmup plus measured repeats. Cold time includes cache
clear, frozen copies and retention accounting; warm time includes hashing all
inputs. Mutations and framebuffer clears are outside the measured draw in every
mode. Moving scenarios use a new position each repeat and require misses. All
color/depth bytes and deterministic plan receipts must match within each frame.

The JSON contains raw samples, median/IQR/unscaled MAD/min/max/n, paired ratios,
per-frame color/depth hashes, per-draw cache receipts, environment and hashes of
all twelve benchmark dependencies. A positive time budget uses a supervised child
and publishes only completed reports; `0` is explicitly unbounded. A failure or
timeout preserves existing output files. `audit(receipt, root=checkout)` checks
statistics, cache bounds and all declared sources. It is an artifact consistency
check, not an independent rerender. Real parity comes from the benchmark draws.

Static benefits, cold overhead and moving-scene losses must be reported together.
Synthetic/procedural results do not establish original-GLB, textured-gameplay,
million-node or gaming-GPU performance. No automatic default activation follows
from a favorable static result. Wolfram may check dependency/depth rules offline;
there are no provider calls in the draw path.

## Test-branch findings (2026-10-11)

The first experiment ran on source commit
`f4ef0f99919b1875ad68d5903598bb8b5b13e9ed`, with Python 3.12.14,
NumPy 2.3.5, an AMD EPYC 9V74 CPU, one renderer worker and a 32 MiB cache.
Each resolution used all five seeded scenes, all three scenarios, 15 measured
repeats and one warmup: 1,350 measured draws / 1,440 draws including warmups.
Source hashes stayed unchanged throughout both runs. Every frame's color/depth
bytes and deterministic plan receipt matched between all three modes.

These are paired median ratios against the uncached draw (greater than 1 is
faster), not ratios of independently selected median times:

| Scene | Static 128 px | Static 256 px | One vertex changed 128 px | One vertex changed 256 px |
| --- | ---: | ---: | ---: | ---: |
| tiny | 1.509 | 1.471 | 0.703 | 0.824 |
| small-triangles | 1.153 | 1.051 | 0.764 | 0.860 |
| large-surfaces | 1.126 | 1.037 | 0.927 | 0.960 |
| procedural400 | 1.116 | 1.055 | 0.827 | 0.861 |
| procedural5k | 1.172 | 1.087 | 0.799 | 0.830 |

All-vertex changes also lost: 0.731–0.966 at 128 px and 0.755–0.964 at
256 px. Cold-cache ratios were 0.687–0.965 and 0.697–0.967 respectively.
Small/sub-millisecond differences and the 3–9% gains at 256 px need repeat
measurements on another machine before a broader recommendation. IQR, MAD,
raw samples and all negative cases are retained in
`evidence/preparation-cache-experiment-v1.json`; the original full benchmark
receipts additionally contain per-frame hashes and per-draw cache state.

The locally executable suite passed 223 tests (two optional-JIT skips), with
100% cache and 96.06% benchmark line coverage; both new files have 95% CI floors.
Two host-only exclusions are explicitly recorded: AF_UNIX creation is denied
here, and the nested full-suite coverage test contains that same socket test.
The final PR-head Linux/Windows/JIT/wheel/Mesa matrix remains the authoritative
complete-suite gate. No test or existing coverage floor was weakened.

Conclusion: retain this as an explicit experiment for repeatedly drawn unchanged
inputs. Whole-draw invalidation, hashing, freezing and retention accounting make
this version unsuitable as a default for changing geometry. Partial updates or
a repeat-based admission policy need a separate measured experiment.
