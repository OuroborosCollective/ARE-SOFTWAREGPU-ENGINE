# MIHA Auto — continuous preparation with immutable training snapshots

The growing public `Thorsu/miha-evidence` dataset is **not** a live-training
iterator. The `auto` Viewer is a one-record projection; the real supervised
fine-tuning examples come only from the approved SHA-pinned canonical-to-Atomic
builder. The older 32-record snapshot produces 557 Atomic examples; the live
archive may grow without a fixed 557-example cap.

## Automatic daily pipeline

`.github/workflows/miha-adaptive-auto.yml` runs daily at **06:17 UTC**,
can be dispatched manually, and runs for changed PRs. It fetches a live
Evidence revision once and pins that SHA for the complete run. It uses the
immutable configured builder and benchmark revisions, rebuilds the previous
approved Atomic SFT snapshot and compares it byte/manifest-exactly with the
published approved Atomic release. It then builds a new **candidate** from
the live canonical files and checks full holdout source, ID and question
overlap with the pinned benchmark.

The candidate is verified by canonical JSONL SHA-256, training row IDs,
canonical origin links, source content hashes, builder revision and total
row count. New rows are detected and organized into deterministic batches,
grouped by canonical origin. The plan includes the **whole corpus** for
replay: existing examples plus newly added examples. Dataset growth has no
artificial global row cap; each replay shard is bounded to 2,048 examples.
A single oversized origin fails closed rather than silently splitting
its provenance.

The artifact contains candidate SFT rows, build manifests, full-replay plan,
source revision, independent SHA-256 receipt and immutable builder/bench pins.
**One training run consumes one version only.** New records appearing during
a run are included in a later snapshot, not silently appended to current
optimizer steps.

## Decision states

- `NO_CHANGE`: no new approved-source difference. No unnecessary retrain.
- `CANDIDATE_READY_FOR_REVIEW`: a complete source-bound Atomic candidate
  exists; it is **not yet a published or approved Atomic revision**.
- `CORRECTION_REVIEW_REQUIRED`: approved rows or source hashes changed or
  disappeared. Affected data must be reviewed before learning.
- `SOURCE_BLOCKED`: canonical files missing, corruption, or holdout
  leakage. Keep the last verified approved snapshot; never train from
  incomplete Auto data.

## Training promotion gate

A candidate becomes suitable for training only after review of the
immutable built row hashes and manifest, publication of a new versioned
Atomic Hub commit, dual remote readback against the pinned builder result,
no benchmark leakage, >=16-GiB host memory, longest-example
forward/backward and real assistant-only loss. After training, reload the
adapter and run **all 20 pinned MIHA-Bench holdout tasks** before promoting
a new model.

The current pinned `train_v2.py` has a fixed rank-16 LoRA, fixed LR 1e-4
and no real Trainer resume. It will **not** automatically train from new
unpublished candidates. Future versioned trainer changes can consume
this immutable plan and optionally warm-start from a verified approved
adapter; blindly reusing an optimizer state across a changed dataset
is disallowed. Replay helps mitigate catastrophic forgetting but does
not prove prevention; holdout performance must verify it.

**Automation is preparation, not training execution.** The current workflow
has `contents: read`, no Hugging Face write token and no GPU/paid compute
launch. Model release remains a separate authenticated and verified action.
