# Experimental CAG → SpherePop → Doppler radial rendering wavefront

An independent Wolfram Language calculation establishes the CAG start at **(3,4)**:

```wolfram
FullSimplify[{(4+5)/3,(11-3)/2,Table[Norm[{dx,dy}],{dx,-1,1},{dy,-1,1}]}]
(* {3,4,{{Sqrt[2],1,Sqrt[2]},{1,0,1},{Sqrt[2],1,Sqrt[2]}}} *)
```

The optional C++17 kernel `native/raster/spherepop_cag_radial_wave.hpp` accepts that seed and iteratively expands an **eight-connected, finite** pixel-area grid. Cardinal neighbors are distance 1; diagonal neighbors have distance sqrt(2). A stable priority queue chooses earliest arrival, breaking ties by cell ID and emitter ID. Each newly finalized area emits a new local wave into the eight neighboring directions until every area is finalized. A completed cell cannot trigger another draw or another wave **within the same invocation**. Competing arrivals are Refuse-like discarded continuations; they do not append another Pop/Collapse, and a positive refusal counter documents them.

This **is a grid approximation to isotropic propagation**, not a continuous circular wave solver. The propagation speed is constant in every permitted direction; a classical radial moving-source Doppler factor only influences the artistic color tint. The source cell has no radial direction, so it has factor 1 and is finalized once without tint. SpherePop is used as an inspiration for one-shot event semantics; it is not a complete implementation of upstream SPHIST/1 or formal proof calculus.

A successful **actual native ARE C++17 raster draw** is used to obtain RGBA8/depth/owner inputs; the native regression verifies 7x9 areas, first-visit-only closure, reproducible replay, CAG (3,4), expected axial ratios {4/3,4/5,1}, sqrt(2)/speed diagonal arrival, untouched background and float32 depth, and invalid-input rollback.

The result is a bounded **render-effect projection**, not new physics/gameplay authority, not new geometry draw calls, not automatic asset import, not an operational audio Doppler effect, and not a speedup claim. It currently has no cross-call persistent completion memory: a separate invocation is a new render frame and may process every point again. Never interpret the per-invocation receipt as globally durable once-only persistence.

## Repro

```bash
python -m unittest software_gpu.tests.test_spherepop_cag_radial_wave -v
python -m unittest discover -s software_gpu/tests -p 'test_*.py' -v
```

Run the full exact-PR-head CI (Linux, Windows, LLVM JIT, Mesa) and check coverage before merge. No uploaded GLB asset is committed. Detailed artifact/performance qualification, cross-frame ownership semantics and real GLB replay are separate requirements before considering the production pipeline.
