---
schedule: every 6h
metric_direction: higher
---

# SoftwareGPU CPU evidence optimizer

## Goal
Find measurable whole-draw CPU raster performance gains under strict RGBA8 and Float32 depth equivalence. The goal is **three complete, versioned candidate-catalog sweeps with no reproducible improvement**, not five consecutive rejected iterations. Errors, missing profiles and pending CI never count toward the plateau. This program is NOT authorized to claim a finished optimization search until an independently checked plateau receipt exists.

## Target
Initially modify only `software_gpu/graphics/batch_shader.py`; do not edit benchmarks, validators, CI, tests, fixtures, Memory.md, deployment files, workflows, secrets, server config, or release paths. One candidate per run. Do not merge or deploy; output accepted changes only to a Draft PR. No VPS, SSH, persistent workers, GPU, Docker daemon, HF training, remote build service or paid infrastructure.

## Candidate catalog (v1)
1. scalar-float32-rgb-conversion
2. batch-rgb-inplace-clamp
3. batch-rgba-allocation
4. batch-broadcast-and-stride
5. shader-call-overhead
6. batch-dtype-fastpath

Each candidate requires evaluation on 5 scenes (tiny, small-triangles, large-surfaces, procedural400, procedural5k) × 64/128 px × 1/2 CPU workers, on the same GitHub-hosted runner, with 2 rounds × 15 alternating baseline/candidate A/B pairs per profile, true complete frame draws. Repeat until every catalog item has a sound verdict for all 20 profiles. Never convert a missing experiment into "no improvement". Accepted improvement resets the no-gain full-sweep counter. After 3 completed gain-free sweeps, halt and record a terminal receipt.

## Evaluation
Before attempting any change, read current repository Memory.md and the validated program state. A genuine evaluator with independent source/commit verification and CI review must exist and pass its own integration test. The evaluator must produce strict JSON with numeric `score` (higher is better), and return nonzero on missing runtime evidence. Never use unit-test fixture values as performance measurements. Require identical color+depth per profile, candidate slowdown no worse than 2%, and independently repeatable >=2% geometric mean improvement. Preserve shader float32 rounding and numerical contracts. Stop rather than trusting a partial evaluation.

## Rank publication
Do not change `evidence/autoloop-accepted-leaderboard-v1.json` directly. The existing `software_gpu.benchmarks.autoloop_publication` gate only accepts complete source-bound receipts with SHA-verified green GitHub CI. The public website only displays verified entries from main after reviewed merge. If a compatible true A/B receipt cannot be generated, no ranking update occurs.

## Resource safety
One iteration at a time. Maximum 45 min per workflow run, bounded disk use, zero VPS traffic, single long-running Draft PR branch, no unbounded artifact retention, no background deployments. Verify every GitHub Actions head after changes. If gh-aw compilation, repo permissions, or runner prerequisites fail, PAUSE and report a concrete blocker; do not improvise bypasses.

## Verified persistent experiment ledger
Maintain a bounded JSON document between the exact HTML markers `ARE_CPU_RUN_LEDGER_BEGIN` and `ARE_CPU_RUN_LEDGER_END` in the repo-memory state file `softwaregpu-cpu.md`. Its protocol is `are.autoloop-cpu-run-ledger.v1`, `catalog_version` must equal `catalog.json.version` and each entry may contain ONLY `sweep`, `candidate` and `run_id`. Never write an agent-derived `ci_verified`, `status`, synthetic timing, or claimed completion flag into this ledger. Run IDs must refer to immutable, successful GitHub Actions `workflow_dispatch` executions of `Autoloop CPU A/B (GitHub runner only)`, with one bounded `raw-600-pairs.json` artifact. The scheduler independently fetches every actual run and artifact via the GitHub API, validates source hashes and profile measurements, and blocks selection if any evidence is missing or invalid. The three-sweep halt is computed exclusively from this verified ledger, not from free-text statuses. Never attempt to bootstrap progress by inventing a run or a benchmark receipt.

Important: until the initial repo-memory ledger exists and the independent GitHub artifact readback passes, scheduled Autoloop intentionally does not select this program. The reference benchmark workflow can be triggered only manually for a real candidate; every candidate must change the allowed shader source, preserve all non-target benchmark source hashes and have an exact green CI/receipt binding. A smoke-pass or two synthetic unit tests are NOT catalog-verdicts.
