# MIHA PyTorch Training Optimization V2 — safe staged rollout

**Status:** Research infrastructure, not a trained or accepted adapter. Existing pinned
[CPU-LoRA training workflow](MIHA_CPU_TRAINING.md) remains unchanged. No new
paid compute, GPU session, training job or Hugging Face publication is started.

## Available in this branch

* `scripts/miha_v2.py plan --renderer-sha <40-hex> --output plan.json` verifies
  pinned Atomic/Evidence/holdout/base revisions and emits nine rank × LR candidates:
  ranks 8/16/32 × learning rates 0.00005/0.0001/0.0002. These are **planned
  experiments**, not completed sweeps. No rows are synthesized and no weights load.
* `scripts/miha_v2.py cpu-profile --threads 2 4 6 8 --width 256 --output profile.json`
  performs real CPU-only PyTorch matrix forward/backward operations and records
  profiler operator self-CPU times and 15 raw timings per thread count. It **does
  not** profile the full Qwen/LoRA model. CPU runtime and PyTorch must be installed.
* `v2_contracts.seal_checkpoint(path, identity)` creates a one-time SHA-256 manifest
  of a **real** Trainer checkpoint (optimizer, scheduler, RNG, adapter and
  trainer_state). `verify_checkpoint` fails closed on changed seed, model/data
  revision, device, rank, thread count, step or file contents. It does **not**
  run `Trainer.train(resume_from_checkpoint=...)`, migrate optimizer state,
  or promise working full-trainer resumption. The older pinned HF train_v2.py
  remains the only authorized training implementation until separately reviewed.
* `scripts/miha_v2.py quality-gate --report eval.json --expected-ids
  holdout-ids.json --bench-revision <40-hex> --output gate.json` checks the
  existing full holdout evaluator's report against actual expected task IDs,
  no regression and source-compliance scores. Passing means only eligibility
  for an **independent acceptance process**, never automatic publication.
* `scripts/miha_v2.py gpu-preflight --policy training_config.json --allow
  --devices 1 --vram-gib 24 --bf16` checks explicit approval and minimum
  resources, without running any GPU workload. The **current pinned MIHA
  policy has `gpu_allowed: false`**: requests correctly fail closed. GPU-mode
  training needs a **separately approved immutable research configuration**,
  kernel tests and a separate PR. Do not change this owner policy implicitly.

## Release sequence and next gates

1. **Current V2 PR:** SHA-bound contracts and real, explicitly opt-in CPU
   operator microprofile. CI tests negative checkpoint tampering, deterministic
   experiment plans, policy refusal and holdout-completeness checks.
2. **Follow-up runtime PR:** modify the pinned trainer under a separately
   versioned model-code revision to accept a validated LoRA rank/LR and
   `resume_from_checkpoint`; perform a real interrupt/resume test comparing
   optimizer steps and assistant-only loss with a continuous CPU run. Preserve
   longest-example backward and >=16 GiB memory gates.
3. **Follow-up evaluation PR:** run **every** existing pinned `miha-bench`
   holdout task with the existing `evaluate_v2.py` baseline/adapter reload
   and exact revision checks. Compare candidate experiments on identical data,
   seeds and code. Quality acceptance requires full holdout, no quality regressions,
   evidence compliance, adapter reload, SHA and remote readback.
4. **Optional GPU research PR:** only after an explicit policy update by the
   owner; train on a separately pinned GPU configuration with a supported
   compute backend. Never treat ARE SoftwareGPU as CUDA/PyTorch autograd.

## Rules

The 557 canonical/Atomic examples and pinned holdout cannot be altered or
intermixed. No truncation, skipping, dataset leakage, fabricated loss values or
automatic acceptance. Avoid `[miha-train]` in ordinary commits: the old push
lane uses that tag to start full paid-time training. Existing `HF_TOKEN` is
used only by the authorized publication step. A local 15-repeat CPU operator
profile is not evidence for LoRA step throughput or GPU acceleration.
