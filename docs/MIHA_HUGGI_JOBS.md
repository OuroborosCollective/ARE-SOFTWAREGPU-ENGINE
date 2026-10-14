# MIHA on Hugging Face CPU Jobs + ARE SoftwareGPU

The integration is **opt-in, immutable and CPU-only**. Hugging Face Jobs executes
PyTorch/PEFT CPU LoRA; ARE SoftwareGPU renders only *actual logged training loss*
as deterministic BMP/HTML/JSONL with SHA-256 receipts. It is **not** a native
GPU, a PyTorch autograd implementation, or a training acceleration claim.

## Existing authority

- Canonical dataset: `Thorsu/miha-evidence`, immutable revision in
  `fixtures/miha/training.json`.
- Atomic SFT: `Thorsu/miha-train-atomic`, pinned separately; **all 557** examples.
- Held-out evaluation: `Thorsu/miha-bench`, 20 cases, never trained on.
- CPU base: `Qwen/Qwen2.5-0.5B-Instruct@7ae557604adf67be50417f59c2c2f167def9a775`.
- Training implementation: pinned `Thorsu/miha-deepseek-r1-distill-qwen-7b-lora` source
  (historical repository name; old DeepSeek and GPU adapters are retired).
- Renderer: the **exact 40-character GitHub checkout SHA**; no `main` or
  latest snapshot inside the job.

## How to run

Open GitHub Actions > **MIHA Huggi CPU Jobs** > Run workflow. `action=plan`
(default) validates inputs and emits `miha-huggi-plan.json` without spending
money. `action=submit` explicitly starts a **billable** Hugging Face CPU Job,
requires the repository Actions secret `HF_TOKEN` with write permission for
`Thorsu`, and first verifies the USD estimate against `max_usd`. Never paste
that token into a ticket, workflow input, URL or chat.

Choose `mode=audit` for pinned canonical/Atomic readback and real SoftwareGPU
raster/receipt tests without model training. Choose `mode=train` for the same
preflight and audit followed by a **complete** one-epoch CPU LoRA run; the
longest-sequence backward gate must pass, with no data truncation or skipping.
After actual optimizer steps, only a *candidate_unvalidated* adapter may be
published under the unique `huggi/jobs/<JOB_ID>/` prefix, where `JOB_ID` is injected by Hugging Face and never overridden by the caller. The pinned
`evaluate_v2.py` then runs the full held-out baseline/candidate comparison,
reloads the adapter, records regressions, and saves immutable evaluator reports
with remote readback. A job failing or timing out is **not** a trained model.

The same launcher can be driven outside Actions:

```sh
python scripts/miha_huggi_jobs.py plan --renderer-sha <FULL_GIT_SHA> \
  --mode train --flavor cpu-upgrade --timeout-hours 6
# Only after checking actual account billing and setting HF_TOKEN securely:
python scripts/miha_huggi_jobs.py submit --renderer-sha <FULL_GIT_SHA> \
  --mode train --flavor cpu-upgrade --timeout-hours 6 \
  --max-usd 0.20 --confirm-paid-job
```

The existing `.github/workflows/miha-cpu-training.yml` remains an independent
GitHub-runner route. The Huggi workflow is *manual only* to prevent accidental
billing on commits, PRs, CI retry, or a schedule.

## Hardware, cost and fail-closed rules

As documented by Hugging Face (checked 2026-10-14), CPU Jobs charge by minute:

| Flavor | CPU | RAM (advertised) | Published USD/hour |
| --- | ---: | ---: | ---: |
| `cpu-upgrade` | 8 | 32 GB | $0.03 |
| `cpu-xl` | 16 | 124 GB | $1.00 |
| `cpu-performance` | 32 | 256 GB | $1.90 |

`cpu-basic` is excluded: its advertised **16 GB decimal** is less than the
unchanged minimum **16 GiB**. The trained model must still pass the real
cgroup/physical RAM and longest-case backward gates; 32 GB is not a promise
of success. The job timeout is at most 24 hours. `max_usd` checks the
published-rate estimate **before submission**, but is **not a provider-enforced
wallet cap**; actual prices/credits must be confirmed at Hugging Face. Jobs
require positive credit balance even if the account is Pro, and may return
`402 Payment Required`. No GPU fallback, automatic retries, or automatic
inference service is enabled.

## Evidence / truth boundaries

`plan` means validated configuration only. `submitted` means the provider
accepted a Job, **not** training success. `AUDIT_PASS` means actual canonical
readback and raster tests, not model quality. Adapter publication requires
actual optimizer steps, CPU manifest and byte-for-byte Hub readback. The final
benchmark must pass parse validity, citation/source compliance, baseline
non-regression and score threshold; failure remains explicit and never
activates an adapter. Neither the renderer's loss chart nor a job URL proves
model quality.

Sources: [HF Jobs API](https://huggingface.co/docs/huggingface_hub/en/guides/jobs),
[HF Jobs prices](https://huggingface.co/docs/hub/jobs-pricing),
[MIHA existing CPU trainer](MIHA_CPU_TRAINING.md).
