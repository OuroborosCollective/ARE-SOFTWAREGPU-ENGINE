# MIHA training on GitHub CPU runners

The **MIHA CPU training** Actions workflow connects the pinned Hugging Face CPU-LoRA implementation to ARE SoftwareGPU. The model trains on CPU PyTorch; ARE's CPU tile rasterizer renders the Trainer's observed loss values. It is not a CUDA device or an autograd backend.

## Start and inspect a run

Open **Actions → MIHA CPU training → Run workflow**. Choose `train` to run the input audit, memory preflight and full training; choose `audit` to verify inputs without training. A push on the integration branch with `[miha-train]` in its commit message also requests training. Ordinary branch pushes and pull requests only run the input audit and renderer tests.

The default `ubuntu-24.04` runner must report **at least 16 GiB** to the unchanged model policy. GitHub advertises 16 GB for public Linux runners; that label does not guarantee the actual byte threshold. If RAM is lower, the workflow records `BLOCKED` before installing ML dependencies or loading model weights. A configured self-hosted Linux x64 CPU runner with labels `cpu` and `miha-32g` is selectable for more headroom. No such runner is provisioned by this change. Both paths still perform the longest-example backward check, with no truncation, skipped examples or GPU fallback.

The workflow trains one full epoch on the **557-example canonical/Atomic release** in `fixtures/miha/training.json`. The current Evidence audit and its newer allowlist are separate from that approved builder snapshot; new evidence is not silently included. The pinned `miha-bench` holdout is read only. No synthetic dataset rows are produced.

## Outputs and publication

Each run provides an input audit and CPU-run artifact containing available RAM receipts, logs, SHA-256 file inventory, the latest two checkpoints and a completed adapter candidate when training actually finishes. Open `metrics/training_metrics.html` for a self-contained chart, axis description and exact values table. The same observations appear in `loss.jsonl`, `loss.bmp` and `render_receipt.json`. Only actual logged steps are plotted. Controlled unit-test chart fixtures are not training results.

The training subprocess stops after 19,000 seconds to leave room for diagnostic artifact upload inside GitHub's six-hour job limit. Checkpoints are retained every five optimizer steps. There is no automatic checkpoint resume; an interrupted run is not labelled complete.

An existing repository Actions secret **HF_TOKEN**, with write access to the Thorsu model, enables candidate publication to a unique `actions/run-<id>-attempt-<attempt>/` prefix and exact file readback. Tokens are supplied only to the publication step. Public-input training and GitHub artifacts require no Hugging Face token. Missing credentials do not manufacture a Hub success receipt, and existing candidate prefixes are not overwritten.

Every trained adapter remains `candidate_unvalidated`, `success: false`. Full held-out evaluation, a fresh adapter reload and verified readback are required for acceptance. This workflow does not claim those gates have passed or promote a candidate to the active model.

## Source and licensing

Hugging Face code, base model, evidence, Atomic dataset and holdout are pinned by 40-character commits. The renderer runs from the exact checked-out GitHub commit recorded in its receipt. Existing ARE PolyForm Noncommercial licensing and OuroborosCollective attribution remain applicable; no source assets or historical evidence records are rewritten.
