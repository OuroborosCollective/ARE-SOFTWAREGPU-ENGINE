# Issue #4 — Mesa llvmpipe CPU comparison

This is a **separate evidence lane**, not a performance promise or a GPU replacement. ScaNN is deliberately out of scope.

## What is actually measured

- Five seeded 32-bit CPU geometry workloads: `micro`, `overdraw`, `game`, `near_clip`, `msaa4`. The exact vertex/color bytes are hashed and passed to both executors.
- `bands`, `tiles`, optional `tiles-jit` and a real Mesa OpenGL 3.3 `llvmpipe` context, **each in a separate process on the same GitHub runner host**.
- Software rendering is forced by `LIBGL_ALWAYS_SOFTWARE=1`, `GALLIUM_DRIVER=llvmpipe` and `EGL_PLATFORM=surfaceless`. The reported `GL_RENDERER` **must** contain `llvmpipe`; otherwise the sample fails closed.
- One initial invocation (including JIT compile where applicable), another warm-up, repeated steady-state frame wall time, process CPU time, median, empirical p95 and Linux process peak RSS (cumulative). 1/2/4/8 requested workers in separate CI jobs.
- Each child returns digest-bound RGB images and structured JSON; comparison records coverage IoU, max/mean RGB error, and parity classification. Failure to generate a renderer, unsupported OpenGL, or mismatched evidence is never replaced with invented timings.

## Differences preventing automatic performance equivalence

- ARE uses Python fragment shading; Mesa uses native compiled GLSL. The shader implementations and full cost breakdown are not identical.
- OpenGL clipping/fill/depth rules may differ at edges. Error is measured, not hidden.
- A real first benchmark discovered 688 near-plane JIT pixels differing from ARE bands by exactly one 8-bit channel step (maximum 1/255). The benchmark marks this as `NUMERIC_ONE_LSB_DIFFERENCE`, records mismatch counts, and fails for deviations larger than one LSB. This is **not** byte-identical rendering and warrants separate numerical-investigation work; no silently substituted output.
- Mesa MSAA sample layout is implementation defined, while ARE has a fixed 2x2 pattern. The `msaa4` scene is therefore **NOT_COMPARABLE_MSAA_SAMPLE_POSITIONS** for direct speed claims.
- Mesa depth buffer is **not read back** in this pilot: `depth_readback=UNVERIFIED`. No depth parity claim is permitted.
- Input VBO transfer is included in llvmpipe timing; ARE memory is already resident but geometry and shading are included. Results are *same host observations*, not an equal-runtime-contract proof.
- Windows WARP is **UNSUPPORTED_NOT_EXECUTED**. Energy readings are **UNAVAILABLE_NO_ENERGY_METER**.
- No comparisons across independent GitHub runner machines should be aggregated into a global speed ranking.
- Empirical p95 from three repetitions is only a diagnostic; a production benchmark would require more samples and controlled pinning.

## CI and local replay

```bash
python -m pip install -e ".[jit]" "moderngl>=5.12,<6"
LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe EGL_PLATFORM=surfaceless \
 python -m software_gpu.benchmarks.external_cpu_benchmark \
 --workers 1 --repeats 5 --jit --output external-cpu-benchmark.json
python -m unittest software_gpu.tests.test_external_cpu_benchmark -v
```

CI runs the same workload on `ubuntu-24.04` with Mesa software OpenGL/EGL and uploads each worker's JSON evidence as an artifact. One benchmark failing is a legitimate failed gate, not grounds to claim that ARE beats Mesa. CI artifacts are evidence only when the reported revision and `GL_RENDERER` are verified.

## Remaining scientific improvements

Fixed CPU affinity; threaded Mesa scheduler readback; a shader-equivalent GLSL/ARE flat shading contract; equivalent timing-boundary microstages; a common depth oracle; multi-resolution MSAA coverage calibration; confidence intervals and a clean on-premises hardware reference host. Until those exist, promote only precisely scoped scene parity observations, **not generalized competitive performance claims**.
