# Issue #286: Offline adaptive SurfacePlanner cost calibration

The existing CPU `SurfacePlanner` and `PreparationCache` remain the only raster execution paths. This change introduces **no second tile/batch implementation and no default policy change**. The existing `tiles` backend remains the default. The calibrated model is a derived, read-only, versioned *policy proposal*, **not** an automatic loader or an active simulation choice.

## Real measurement and exact contract

`software_gpu.benchmarks.compare_surface_plans` now supports `--scene-set training|holdout`. Both sets use independently specified fixed geometries; the training set retains the five older scenes and the holdout set has four previously unseen geometries. The command's four scan/batch factorial paths **all use exactly the same `VertexColorShader` class**, with scan and batch toggled only through immutable `SurfacePlanPolicy` thresholds. The draw-level fallback is disabled for all four, and real shader calls / scan counters are checked. Old `tiles`, `plan-scalar`, `plan-batch`, and `batch-first` comparisons remain available. All draws retain triangle submission order, current depth semantics, same framebuffer clear, identical shader function and NumPy Float32 evaluation. Color RGBA8 and Float32 depth are compared **byte-for-byte**, with separate SHA256s in the receipt. The measured region includes mesh preparation, planning, rasterization, shading and receipt generation.

Training and holdout each require **15 complete interleaved pairs or more** for *every* scene/mode. Real measured time arrays, medians, IQR, unscaled MAD, per-mode counters and both performance-positive and negative results are retained. No FPS extrapolation or hardware GPU parity is claimed. GitHub Actions runs the full pair of measurements on one runner and publishes its raw JSON, HTML, model and audit reports as SHA/attempt-labelled artifacts. The Python source manifests in each report are checked against the **exact checkout**, and both sets must report identical CPU environment, affinity count, Python version, NumPy version/build and thread settings. The `source-revision` must equal `git rev-parse HEAD` of that same checkout.

### Explicit CPU workflow

```bash
python -m software_gpu.benchmarks.compare_surface_plans --output-dir /tmp/are-train --scene-set training --ablation --repeats 15 --pixels 64 --workers 1 --max-seconds 900
python -m software_gpu.benchmarks.compare_surface_plans --output-dir /tmp/are-holdout --scene-set holdout --ablation --repeats 15 --pixels 64 --workers 1 --max-seconds 900
python -m software_gpu.benchmarks.calibrate_surface_costs --training /tmp/are-train/surface-plan-benchmark.json --holdout /tmp/are-holdout/surface-plan-benchmark.json --root . --source-revision "$(git rev-parse HEAD)" --output /tmp/fresh-cost-model.json
```

## Bounded, deterministic selection

`calibrate_surface_costs.py` is offline-only. It validates raw CPU samples, two separate image/depth hashes, source code SHA-256, full benchmark-draw receipts and mutually disjoint training/holdout scene specifications; it rejects missing/NaN/nonpositive/out-of-range times, short samples, misconfigured scan/batch modes, mismatch in environment or source, and any color/depth mismatch. It creates a canonical SHA-256-bound frozen model. The cost weights are actual median **milliseconds per predicted bounding-box sample**, **not** execution counters such as `shaded_samples`, `batch_fragment_calls`, or depth outcomes.

Admissible pre-draw features are only prepared triangle count and estimated bounding-box samples per triangle, already available in `SurfacePlanner`. Frozen finite bins are `tiny/middle/dense` by triangle count and `small/medium/large` by coverage. Each bin's measured winner is eligible only if training's paired median beats unchanged scalar/no-scan by at least **8%**, and independent holdout's paired median beats it by at least **5%**, with first-quartile ratio no worse than 1.0. Missing or negative evidence disables the entire bin. This is conservative local holdout selection, not proof of universal optimization. No gain is claimed unless the actual CI artifacts show it.

`select_replay_policy(model, triangles=..., bbox_samples=..., shader=..., expected_source_revision=...)` uses only immutable model bytes and pre-draw inputs; there are no clocks, unseeded randomness, network calls, or mutable global learning weights in the decision. It returns an existing `SurfacePlanPolicy` for a validated bin and explicit equivalent batch shader, or `None` to preserve the reference backend. A stale source revision or a model digest mismatch **raises**, never silently activates another path. **The generated model is not automatically installed or enabled.** The caller must explicitly evaluate the frozen model before selecting `backend='tiles-plan'` and provide the returned policy. Do not use unvalidated model output in game authority or a deterministic tick.

## Evidence and non-goals

- **Tests:** `software_gpu/tests/test_surface_cost_calibration.py` exercises frozen replay, malformed model/digest, SHA drift, bad timings, parity failures, short pairs, disjoint holdouts and reference-only negative holdout.
- **CI:** `.github/workflows/issue286-surface-cost.yml` runs real train+holdout with 15 repeats, independent Workbench audit, and posts the archive. Real CI and main merge must be read back at the exact head. A synthetic test receipt does not prove real raster performance.
- **Project surfaces:** production defaults unchanged; tests and derived offline benchmark persistence added; deterministic core reads only an immutable `SurfacePlanPolicy`; shader/effect/depth semantics preserved; runtime/gameplay projection is **not** altered.
- **Limits:** No activation on unrecognized geometries, unknown/stateful shaders, unvalidated scenes/CPU, stale revisions, invalid source hashes or absent holdout. `PreparationCache` remains opt-in, and its existing key/invalidation rules are unchanged. No partial-update cache and no new renderer authority.
