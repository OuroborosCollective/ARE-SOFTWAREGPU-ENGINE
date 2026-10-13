# Native Bio-frontier cache and memory-order research

**Experimental only; production C++17 raster/Float32/depth defaults remain unchanged.**
The exact changes live in `native/symbolic/bio_workrooms.hpp`, built through
`software_gpu/research/bio_workrooms.py`. No release, renderer speedup or
formal C++ happens-before proof is claimed from a successful test alone.

**Follow-up actual worker-stats measurements:** [40-case evidence and negative results](BIO_WORKER_STATS_CACHE_PILOT_20261013.md).\n\n**First real 32-case exploratory results:** [source-bound benchmark, medians and negative cases](BIO_FRONTIER_CACHE_PILOT_20261013.md). The measured GitHub host had four logical CPUs and 8-worker oversubscription; no production improvement is inferred.

## Current real code / hypotheses

- `pending_` is `atomic<unsigned char>[]`, one 1-byte dependency
  counter per AA tile; each predecessor calls `fetch_sub(1, acq_rel)`.
  This is **already acquire/release**, not the default `seq_cst`.
- `CheckpointLedger::stamps_` is a separate packed `atomic<uint64_t>[]`
  with checked CAS transitions; generation tickets are **not** rewritten.
- `CheckpointLedger::completed_` is one genuine shared atomic address;
  padding it would not fix **true contention** on the same location.
  `jobs_`/`samples_` are plausible distinct-worker false-sharing candidates
  and should be investigated separately.
- The native scheduler uses a `fetch_add(32, relaxed)` cursor. A 1/2/4/8
  worker speedup cliff is diagnostic only; it is not proof of false sharing.

## Compile-time A/B controls

`build_bio_workrooms(path, ablation=...)` explicitly allows exactly five
variants and records the compiler flags and binary SHA-256:

| Variant | Per-AA-tile `pending_` layout | Handoff |
| --- | --- | --- |
| `default` | densely packed unsigned-byte atomics | `fetch_sub(acq_rel)` |
| `padded-pending` | `alignas(64)` one atomic per 64-byte stride | `fetch_sub(acq_rel)` |
| `release-fence` | packed | `fetch_sub(release)`, acquire fence only when old==1 |
| `padded-release-fence` | padded | release plus conditional acquire fence |
| `padded-worker-stats` | packed | `acq_rel`, disjoint 64-byte-aligned worker jobs/sample counters |

The `release-fence` and `padded-release-fence` variants rely on the **C++17 release-sequence and atomic-fence
synchronization contract**: all predecessors must publish resolved tiles before
the release RMW, every decrement must participate in the same release sequence,
and the winning RMW reading the last predecessor value must precede the acquire
fence. See [the C++17 fence wording](https://timsong-cpp.github.io/cppwp/std17/atomics.fences).
A DAG check alone is not a memory-model proof; ThreadSanitizer and real
multi-worker parity tests are separate checks. Production default stays unchanged.
Do **not** treat `relaxed` generation loads or unconditional ticket stores as
valid substitutes for the current CAS/checkpoint checks.

Padding can **hurt**. At 640×640 with one-pixel tiles there are 409,600
pending counters: packed is about 0.39 MiB, 64-byte stride about 25 MiB.
At 16×16 tiles, 1,600 entries cost ~1.56 KiB versus 100 KiB.
These figures cover pending counters only, not the rest of the renderer.

## Actual native tests and measurements

```bash
ARE_BIO_CACHE_ABLATION_TEST=1 python -m unittest \
    software_gpu.tests.test_bio_frontier_cache_ablation -v

python tools/benchmark_frontier_cache.py \
    --output-dir /tmp/are-bio-cache --repeats 15 --max-seconds 1200 \
    --workers 1 2 4 8 \
    --variants default padded-pending release-fence padded-release-fence
```

The native binary itself renders the actual clipped seeded test geometry
and checks every frame against its frozen C++17 single-worker oracle.
The isolated C++17 build variants are also checked against the independent
Python renderer on real RGBA/depth buffers in the regression suite. Compiler
and input SHA-256, source SHA-256, raw frame medians, IQR/MAD, complete
frame digest, worker count and binary digest go into
`/tmp/are-bio-cache/benchmark.json`. The input wire files
`*.request.bin` are saved for hardware profiling. All cases/variants remain
in the report, including regressions. Measurements are **serial**, and
`--max-seconds` is a bounded per-sweep admission budget, not a kill signal
inside a single native process.

There are two bounded test fixtures: 128×128 1-pixel sparse triangles,
and 256×256 16-pixel large triangles. These are not the original PBR GLB arena.
The historical frozen baseline has a different scheduler; compare
candidate variants **at the same host, scene, worker count and build** rather
than inferring false sharing from historical-baseline ratios alone.

### Cache-to-cache profiling (optional Linux host, not GitHub-hosted proof)

Run only on a supported **isolated** Intel/AMD/Arm Linux benchmark host with
performance PMU permissions. Verify `perf c2c record -e list`; CPUs,
kernel/perf and virtualization can make the feature unavailable.
Use a saved **actual** native build and native request from the above run:

```bash
out=/tmp/are-bio-cache
perf c2c record -o "$out/perf.data" -- \
    "$out/build/default/bio_workrooms" 4 15 combined \
    < "$out/sparse64-tile1.request.bin" > "$out/perf-response.bin"
perf c2c report -i "$out/perf.data" --stdio > "$out/perf-report.txt"
```

Compare packed versus padded binaries with the **identical** input/affinity,
then associate HITM/cache-line offsets with `pending_`, `stamps_` and
per-worker counters through symbols and `pahole`/source. HITM is sampled
cache-coherence telemetry, **not a causality proof**. A low HITM count does
not prove absence of contention or perfect multicore scaling.
[Linux kernel false-sharing guidance](https://docs.kernel.org/kernel-hacking/false-sharing.html).

### Admission requirements before merging any optimized default

- Full native RGBA, resolved color and float32 depth parity across workers,
  tile sizes, duplicate ticket/recovery cases and all current named policies.
- Linux/Windows C++17 builds, TSAN/ASAN/UBSAN where supported, no hidden
  change to first-submission ties, workload budgets or non-finite rejection.
- 1/2/4/8 worker paired repeats on a stable CPU with fixed affinity,
  documented instruction/CPU limits, no simultaneous benchmark jobs;
  inspect separate CPU-time and wall-time scaling and IQR/MAD.
- Native source/binary/receipt readback plus final head GitHub CI; measure
  performance on an actual benchmark host before deciding whether a
  padded or fence variant should replace the default.

The isolated research branch intentionally does **not** select a winning
policy or claim higher speed before those measurements exist.

## Follow-up: isolated per-worker stats variant

`padded-worker-stats` isolates only the `jobs` and `samples` counters of
individual workers behind 64-byte alignment (verified at native compile time).
The default layout and scheduler remain unchanged. This does **not** pad the
shared checkpoint or pending counters and does not claim to solve genuine
contention. The normal native oracle suite builds the additional variant and
checks resolved, RGBA and float32 depth against the independent renderer.
Performance admission requires comparing candidate medians *on the same GitHub
runner* per scene and workers with the default (not ratios against the
frozen historic renderer), inspecting negative cases, raw 15-sample timings
and output identity; otherwise no production activation.

## Static frontier 32-tile cyclic partition (research only)

New opt-in build switch `ARE_BIO_STATIC_FRONTIER_CHUNKS=1` maps disjoint
32-tile chunks to workers by round-robin worker index instead of fetching
from a shared atomic cursor. The AA predecessor completion counters, release
sequences, checkpoint ledger, per-tile rendering, shader and Float32 contracts
are unchanged. This switch is **not active in production**.

The additional native test uses 1/2/4/8 workers, >32 real chunks, independently
computed exact per-worker raster job ownership and independent Python oracle
resolved/RGBA/depth buffers. GitHub-hosted research workflow builds every
variant, then runs true 15-pair native measurements for default and static
variant on identical scenes. Variant builds run sequentially; their timings
are **not pairwise alternated across the two builds**. Consequently a successful
run establishes parity but not controlled performance superiority. The first
objective is to validate the ownership and shared-dependency model. Full
scheduler promotion remains blocked pending alternating-variant A/B and a
controlled CPU-affinity comparison with negative cases retained.

## Reproducible alternating default/static C++17 runs (PR #61)

The `tools/benchmark_frontier_alternating.py` evidence worker now performs **15 actual
AB/BA rounds** per native scene and worker count, instead of merely sweeping
all default frames before the entire static variant. Each C++17 child process
runs the recorded three warmups and exactly one timed frame, then alternates
which variant runs first on the next pair. The tool checks exact resolved/RGBA/
Depth bytes, handoff state, the source input hash, build binary hashes, and
all raw candidate timing samples before saving a SHA256-signed JSON report.

The benchmark uses the same GitHub-hosted runner per AB/BA test (1/2/4/8 workers)
and serial execution across native test, alternating benchmark, older pilot and
full variant sweep. Each phase has independently captured source and binary
SHA256s. **A/B alternation is not randomization**; this does not prove noise-
free speedup, PBR workload generalization, absence of false sharing or any
hardware-GPU equivalence. No production default switch is authorized from
these CPU-only experiments. Negative cases and 8-worker CPU oversubscription
must be reported without filtering.

## Actual alternating AB/BA native receipt (PR #61)

At head `7523b00baba995266787a69a3841db89d366b274`, GitHub Actions
[38356963320](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38356963320)
completed the serial 15-pair × 2-scene × 1/2/4/8-worker **real C++17**
AB/BA benchmark, including SHA256 checked complete JSON artifact
[11793108409](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions/runs/38356963320/artifacts/11793108409).
The GitHub artifact ZIP SHA256 is
`53ee92ebdef6d9b20ac519c607cb4f8fb4b7d96f3accd1d62705862bbc4a5701`,
and the source-/order-/data-verified JSON receipt digest is
`d215325b1f2d9ae23e6b90f246d903f0f00bf998055fe8921ddbb8677f64f217`.
Each paired round alternates the order (AB, BA), executes the two pinned native
binaries, warms the pipeline and verifies identical resolved, RGBA and depth
output bytes; negative pairs are retained. No claim of hardware GPU parity.

| Native scene | Workers | Default median ms | Static median ms | Static faster pairs / 15 |
|---|---:|---:|---:|---:|
| sparse64-tile1 | 1 | 5.854 | 5.901 | 0 |
| sparse64-tile1 | 2 | 5.382 | 4.891 | 13 |
| sparse64-tile1 | 4 | 3.574 | 3.519 | 11 |
| sparse64-tile1 | 8 | 3.855 | 4.090 | 2 |
| large4-tile16 | 1 | 6.695 | 6.700 | 6 |
| large4-tile16 | 2 | 3.822 | 4.354 | 2 |
| large4-tile16 | 4 | 3.221 | 3.376 | 3 |
| large4-tile16 | 8 | 3.395 | 3.863 | 4 |

**Disposition:** The optional research build is functionally valid, but
performance is workload-dependent, with six of eight scene/worker cells slower
by the median comparison. **Do not activate the static scheduler by default.**
The GitHub runner exposes four logical CPUs; eight workers oversubscribe it.
The AB/BA sampling is ordered, not randomized, and does not control frequency,
thermal or background contention. Native framebuffer parity does not establish
independent GLB/PBR or hardware-GPU parity. This remains a research observation,
not an authorization to change production policy.
