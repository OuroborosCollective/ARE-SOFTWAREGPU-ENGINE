# TabFM: isolated offline research on ARE CPU evidence

**Status:** Experimental, read-only, CPU-only, no renderer/runtime integration.
This is an optional analysis of existing source-bound *historical* CPU receipts.
It cannot change the C++17 scheduler, shader, gameplay state, 10-Hz tick, or
production renderer policy.

## Real source and train/test boundary

The input is `evidence/native-raster-surface-plan-metrics-v1.json`
(protocol `are.native-raster-surface-plan-metrics.v1`). It contains five real
scene families, eight execution plans and fifteen raw paired timings per plan.
The evaluator checks positivity, finiteness, receipt median versus raw samples,
complete plan balance, actual image parity and absence of GPU parity claims.
Source bytes and extracted observation rows are independently SHA256-recorded.

Each of five leave-one-**scene**-out folds trains on all four other scenes
(32 observations), and predicts eight plan medians for the held-out scene.
No repeated timing samples from the same scene enter both sides.
Only **triangles, pixels, workers, plan** are model inputs; observed timing,
fragment counters, shaded samples and scene labels are not model features.
Outputs include all predictions and per-fold MAE/sMAPE; no filtering of losses
or negative examples. An offline prediction is *never* a runtime activation gate.
Limited scene variety prevents credible generalization claims.

## No-model baseline on GitHub-hosted worker

```bash
python -m unittest software_gpu.tests.test_tabfm_benchmark -v
python -m software_gpu.research.tabfm_benchmark \
  --input evidence/native-raster-surface-plan-metrics-v1.json \
  --mode baseline --output /tmp/tabfm-baseline.json
```

The baseline is the per-plan median of the other four scenes. It uses only
Python's standard library. The dedicated GitHub Actions workflow
`.github/workflows/tabfm-offline-research.yml` runs the baseline and tests on
pull requests affecting the module, then uploads its full JSON receipt.
No VPS, SSH, credential, external model fetch, simulated performance data or
production deployment is involved.

## Restricted TabFM research adapter (not run by default)

- The TabFM **source** is Apache-2.0. The default **pretrained weights** use
  `tabfm-non-commercial-v1.0`, restricted to noncommercial,
  **nonproduction** use. A commercial deployment or unlicensed research use
  must **not** enable this mode. Checking a box does not confer legal rights.
- The source commit is pinned to
  `google-research/tabfm@fbb665569425fd2f490c6576b3af967876fe11ff`.
  The external source and dependencies are installed only by an explicitly
  triggered optional GitHub Actions job, never in the default CPU CI.
  Checkpoint bytes are downloaded by upstream at runtime and are never
  committed, published or uploaded as workflow artifacts.
- To run an authorized, strictly noncommercial evaluation choose the manual
  GitHub workflow inputs `run_tabfm=true` and
  `noncommercial_rights_confirmed=true`. The Python code additionally
  requires `ARE_TABFM_NONCOMMERCIAL_RESEARCH=1` and
  `--confirm-research-rights`, checked **before reading files/importing TabFM**.
  The source is CPU PyTorch; no GPU access and no production credentials.
- Baseline and TabFM both use whole-scene holdout and the same inputs. The
  upstream estimator uses one seeded context ensemble and at most 100 context
  rows; more rows fail closed rather than silently sample. Inference cost
  includes a separate model-load time, and no unproven speed or accuracy
  improvement is asserted.
- GitHub-hosted runner CPU contention, just five scene families, historical
  source hashes, CPU-only comparisons, hardware diversity and commercial
  licensing remain explicit limitations. Do not interpret successful receipt
  validation as rerender or proof of hardware GPU parity.

Upstream: https://github.com/google-research/tabfm (README license section).
