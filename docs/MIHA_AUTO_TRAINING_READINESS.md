# MIHA Auto training readiness — separate from model training

The Hugging Face `Thorsu/miha-evidence` **auto** split contains projections of canonical
research evidence. This is **not** the tokenizer-ready supervised training split.
This is a continuously changing dataset: **never hard-code a live row count**.
A Hugging Face Hub inspection on 2026-10-14 saw 61 current Auto
projections but only 60 matching canonical JSON files. The independent
historical [Notion Dataset-Abgleich (2026-10-09)](https://app.notion.com/p/3f45a669363581d48ec9fe3666403fd2)
describes a different earlier Viewer repair (50 canonical / 51 Viewer,
40 audit-eligible records in its *dated* allowlist). It does **not** certify
the currently missing canonical file. The present missing-canonical ID is
`miha-74d7b5264698de2e31d30b38`; never manufacture the canonical source
from a compressed projection.
Use `pair_coverage` only as an unverified *diagnostic* separating matched
filenames from missing canonical/Viewer filenames. A positive filename
pair count **never** authorizes training. The entire candidate remains
`AUTO_SOURCE_INVALID` or `SOURCE_BLOCKED` until all source, schema,
graph, and content checks pass. The approved historical Atomic snapshot
remains independently auditable and unchanged.
See also [MIHA SoftwareGPU research, 2026-10-14](https://app.notion.com/p/3f95a6693635810b96c2d76836d27c96).

The existing approved frozen source `fixtures/miha/training.json` refers to a
historical canonical snapshot (32 source records) which produced 557 immutable
`Thorsu/miha-train-atomic` SFT examples. Those 557 rows are derived by the
pinned builder, NOT 557 auto evidence research records.

## Before any next long MIHA CPU-LoRA training

1. Run the existing pinned full canonical->Atomic audit:
   `python -u scripts/miha_cpu_runner.py audit --output <new-folder>`.
   It validates the approved 557 examples, original source closures,
   data hashes and held-out benchmark overlap. It does **not** include newer
   auto research by accident.
2. Run the live Auto inventory read-only:
   `python -m software_gpu.training.auto_readiness --output <new-folder>/readiness.json`.
   It fetches only the approved SHA and a separately pinned *current* HF SHA,
   checks actual canonical/viewer file pairs and writes a SHA-bound receipt.
   The receipt always states `training_started: false`.
3. If `AUTO_REFRESH_REQUIRED`: a new immutable canonical Evidence SHA,
   builder revision, reviewed holdout overlap and new Atomic publish/readback
   are required in a separate versioned dataset PR. Do **not** simply point
   the existing 557-example config at `main`, copy the Viewer JSONL into
   training, or change input rows without the builder verification.
4. If `PINNED_CURRENT`: it means the live and configured Evidence SHAs match,
   **not** that every quality, RAM or trainer gate has passed. Confirm
   source-bound input audit, >=16-GiB memory and longest-example backward,
   and complete holdout evaluation after the training run.
5. Training uses CPU under the pinned HF owner policy.
   The PyTorch V2 checkpoint receipt checks integrity, but genuine
   `Trainer.train(resume_from_checkpoint=...)` still needs a separate,
   fully tested pinned training-script revision. GPU jobs are not authorized
   by the current CPU-only model contract.

The CI readiness job downloads actual public Hub records; network/provider
outages fail closed. Historical evidence remains unchanged. No paid Jobs,
adapter training, model publication or release promotion runs in this PR.
